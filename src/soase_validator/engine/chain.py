"""Layer chain resolution.

A Chain is the ordered stack of Layers a Project builds on, lowest first and
the Project last. It is built only from configuration: the Project's
``layers`` list (paths and ``@alias`` entries), the ``extends`` entry of each
Layer directory's own ``soase.json``, the Reference Root of the Project's
Game Version and the Project's Mod Roots. Game state files are never read.

Resolution splices the parents named by ``extends`` beneath their Layer
depth-first, drops repeated Layers keeping the lowest position, adds the
Reference Root below everything and the Mod Roots above everything when they
are not already present, and marks each Layer ``ok``, ``missing`` or
``unusable``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from soase_validator.engine.config import (
    ALIAS_PREFIX,
    PROJECT_FILE_NAME,
    ResolvedSettings,
    expand_path,
)
from soase_validator.engine.diagnostics import C010, C020

EXTENDS_KEY = "extends"

_CURRENT_DIRECTORIES = (
    "ConvertXSI",
    "Galaxy",
    "Galaxy Forge",
    "GameInfo",
    "Launcher",
    "Localizations",
    "Mesh",
    "Particle",
    "Particle Forge",
    "PipelineEffect",
    "TextureAnimations",
    "Textures",
    "Window",
)

_LEGACY_DIRECTORIES = ("Font", "Sound", "String")

#: Single definition of the top-level directory names of game data.
GAME_DATA_DIRECTORIES = (*_CURRENT_DIRECTORIES, *_LEGACY_DIRECTORIES)

LayerKind = Literal["game", "mod", "project"]
LayerStatus = Literal["ok", "missing", "unusable"]


@dataclass(frozen=True, slots=True)
class Layer:
    """One directory in a Chain.

    Attributes:
        name: Alias with its leading ``@`` for an alias entry, else the
            directory name.
        path: Absolute directory. An alias that is not defined keeps the
            alias text as its path.
        kind: ``game`` for the Reference Root of the Project's Game Version,
            ``project`` for a Mod Root of the Project, else ``mod``.
        status: ``missing`` when the directory does not exist, ``unusable``
            when a game Layer holds no game data directory, else ``ok``.
    """

    name: str
    path: Path
    kind: LayerKind
    status: LayerStatus


@dataclass(frozen=True, slots=True)
class ChainProblem:
    """A problem found while building a Chain.

    Attributes:
        code: Diagnostic code, ``SOASE-C010`` or ``SOASE-C020``.
        message: Human-readable description naming the Layers involved.
        path: The Layer path or configuration file the problem concerns,
            or None.
    """

    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class Chain:
    """A resolved Layer chain.

    Attributes:
        layers: Layers from lowest to highest; the Project last.
        complete: True when no Layer other than the Project is ``missing``
            or ``unusable``. A Chain without a game Layer can be complete.
        problems: Cycles and missing or unusable Layers, one entry each.
    """

    layers: tuple[Layer, ...]
    complete: bool
    problems: tuple[ChainProblem, ...] = ()


@dataclass(frozen=True, slots=True)
class _Entry:
    """A Layer reference before status is known."""

    key: str
    name: str
    path: Path
    defined: bool = True


def resolve_chain(settings: ResolvedSettings, env: Mapping[str, str] | None = None) -> Chain:
    """Build the Chain for resolved settings.

    Args:
        settings: The Project's resolved settings.
        env: Environment used to expand paths in ``extends``; defaults to
            ``os.environ``.

    Returns:
        The Chain, lowest Layer first.
    """
    env = os.environ if env is None else env
    return _Builder(settings, env).build()


def looks_like_game_data(path: Path) -> bool:
    """Tell whether a directory holds at least one game data directory.

    Args:
        path: The directory to inspect.

    Returns:
        True when a subdirectory has one of the ``GAME_DATA_DIRECTORIES``
        names, compared case-insensitively.
    """
    wanted = {name.casefold() for name in GAME_DATA_DIRECTORIES}
    try:
        return any(child.is_dir() and child.name.casefold() in wanted for child in path.iterdir())
    except OSError:
        return False


def reference_root_problem(path: Path) -> ChainProblem | None:
    """Check a game Reference Root with the rules the Chain applies.

    Args:
        path: The absolute Reference Root directory.

    Returns:
        A ``SOASE-C020`` problem naming the path when the directory does not
        exist or holds no game data directory, otherwise None.
    """
    if not path.is_dir():
        return ChainProblem(C020, f"Reference Root does not exist: {path}", path)
    if not looks_like_game_data(path):
        return ChainProblem(
            C020, f"Reference Root does not look like a game data directory: {path}", path
        )
    return None


class _Builder:
    """Build one Chain from settings."""

    def __init__(self, settings: ResolvedSettings, env: Mapping[str, str]) -> None:
        """Store the inputs.

        Args:
            settings: The Project's resolved settings.
            env: Environment used for path expansion.
        """
        self._settings = settings
        self._env = env
        self._problems: list[ChainProblem] = []
        self._cycles: set[tuple[str, ...]] = set()

    def build(self) -> Chain:
        """Run the resolution steps.

        Returns:
            The Chain.
        """
        settings = self._settings
        entries: list[_Entry] = []
        for text in settings.layer_specs:
            entries.extend(self._splice(self._entry(text, Path.cwd()), ()))

        mod_roots = [self._path_entry(root) for root in settings.mod_roots]
        listed = {entry.key for entry in entries}
        for root in mod_roots:
            if root.key not in listed:
                entries.extend(self._splice(root, ()))
                listed = {entry.key for entry in entries}

        game_root = settings.reference_roots.get(settings.game_version)
        game = self._path_entry(game_root) if game_root is not None else None
        if game is not None and game.key not in listed:
            entries.insert(0, game)

        unique: list[_Entry] = []
        seen: set[str] = set()
        for entry in entries:
            if entry.key not in seen:
                seen.add(entry.key)
                unique.append(entry)

        project_keys = {root.key for root in mod_roots}
        game_key = game.key if game is not None else None
        layers = tuple(self._layer(e, project_keys, game_key) for e in unique)
        for layer in layers:
            if layer.status != "ok":
                self._problems.append(
                    ChainProblem(
                        C020,
                        f"Layer {layer.name} is {layer.status}: {layer.path}",
                        layer.path,
                    )
                )
        complete = all(layer.status == "ok" for layer in layers if layer.kind != "project")
        return Chain(layers, complete, tuple(self._problems))

    def _layer(self, entry: _Entry, project_keys: set[str], game_key: str | None) -> Layer:
        """Classify an entry and check its directory.

        Args:
            entry: The entry.
            project_keys: Keys of the Project's Mod Roots.
            game_key: Key of the Reference Root, or None.

        Returns:
            The Layer.
        """
        kind: LayerKind = "mod"
        if entry.key in project_keys:
            kind = "project"
        elif entry.key == game_key:
            kind = "game"
        status: LayerStatus = "ok"
        if not entry.defined or not entry.path.is_dir():
            status = "missing"
        elif kind == "game" and not looks_like_game_data(entry.path):
            status = "unusable"
        return Layer(entry.name, entry.path, kind, status)

    def _entry(self, text: str, base: Path) -> _Entry:
        """Turn a configured Layer entry into an Entry.

        Args:
            text: A path or an ``@alias``.
            base: Directory that relative paths resolve against.

        Returns:
            The Entry. An alias without a definition is not ``defined``.
        """
        if text.startswith(ALIAS_PREFIX):
            alias = text[len(ALIAS_PREFIX) :]
            target = self._settings.aliases.get(alias)
            if target is None:
                self._problems.append(
                    ChainProblem(C020, f"Layer alias {text} is not defined in the user file")
                )
                return _Entry(text.casefold(), text, Path(text), defined=False)
            entry = self._path_entry(target)
            return _Entry(entry.key, text, entry.path)
        return self._path_entry(expand_path(text, base, self._env))

    @staticmethod
    def _path_entry(path: Path) -> _Entry:
        """Build an Entry for a directory path.

        Args:
            path: The absolute directory.

        Returns:
            The Entry, keyed by its normalised path.
        """
        key = os.path.normcase(os.path.normpath(str(path)))
        return _Entry(key, path.name or str(path), path)

    def _splice(self, entry: _Entry, stack: tuple[_Entry, ...]) -> list[_Entry]:
        """Expand an entry into its ``extends`` parents followed by itself.

        Args:
            entry: The entry to expand.
            stack: The entries being expanded above this one.

        Returns:
            Entries from lowest to highest. A repeated entry on the stack
            yields nothing and records a ``SOASE-C010`` problem.
        """
        keys = [e.key for e in stack]
        if entry.key in keys:
            cycle = (*stack[keys.index(entry.key) :], entry)
            names = tuple(e.key for e in cycle)
            if names not in self._cycles:
                self._cycles.add(names)
                chain = " -> ".join(str(e.path) for e in cycle)
                self._problems.append(
                    ChainProblem(C010, f"Layer extends cycle: {chain}", entry.path)
                )
            return []
        result: list[_Entry] = []
        if entry.defined:
            for text in self._read_extends(entry.path):
                result.extend(self._splice(self._entry(text, entry.path), (*stack, entry)))
        result.append(entry)
        return result

    def _read_extends(self, directory: Path) -> list[str]:
        """Read the ``extends`` list of a Layer directory's ``soase.json``.

        Args:
            directory: The Layer directory.

        Returns:
            The entries, lowest first. Empty when the file or key is absent
            or malformed; a malformed value records a problem.
        """
        file = directory / PROJECT_FILE_NAME
        if not file.is_file():
            return []
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            self._problems.append(ChainProblem(C020, f"Cannot read {file}: {error}", file))
            return []
        if not isinstance(data, dict) or EXTENDS_KEY not in data:
            return []
        value = data[EXTENDS_KEY]
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            self._problems.append(
                ChainProblem(
                    C020, f"{EXTENDS_KEY} in {file} must be a list of non-empty strings", file
                )
            )
            return []
        return value
