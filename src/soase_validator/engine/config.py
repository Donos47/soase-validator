"""Settings resolution and configuration file helpers.

Each setting is resolved on its own, highest precedence first: project
``soase.json`` files (the nearest first, then each one above it), environment
variables, editor-supplied settings, the user-level file and built-in
defaults. An invalid value yields a ``ConfigProblem`` naming the setting and
the setting takes its default; other settings are unaffected.

Relative paths in a file resolve against the directory holding that file.
Paths from environment variables and editor settings resolve against the
directory of the nearest ``soase.json``, or the start directory when there is
none. A leading ``~`` and ``%VAR%``, ``$VAR`` and ``${VAR}`` references are
expanded before a path is made absolute.

Environment Variables:
    SOASE_VALIDATOR_GAME_VERSION: Game Version name.
    SOASE_VALIDATOR_LANGUAGE: Localization folder name, for example ``en``.
    SOASE_REFERENCE_ROOT_<VERSION>: Reference Root for a Game Version, where
        ``<VERSION>`` is the enum member name, for example
        ``SOASE_REFERENCE_ROOT_REBELLION_198``.

The module reads configuration files and the directory listing used to find
the default Mod Root; it never reads game state files.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import platformdirs

from soase_validator.engine.model import Severity
from soase_validator.engine.primitives import NumericPrefs
from soase_validator.engine.versions import DEFAULT_REBELLION, GameVersion, parse_game_version

PROJECT_FILE_NAME = "soase.json"
USER_FILE_NAME = "config.json"
APP_NAME = "soase-validator"
ENV_GAME_VERSION = "SOASE_VALIDATOR_GAME_VERSION"
ENV_LANGUAGE = "SOASE_VALIDATOR_LANGUAGE"
DEFAULT_LANGUAGE = "en"
ENV_REFERENCE_ROOT_PREFIX = "SOASE_REFERENCE_ROOT_"
ALIAS_PREFIX = "@"

_MANIFEST_SUFFIX = ".manifest"
_MANIFEST_SEVERITIES = (Severity.ERROR, Severity.WARNING, Severity.INFO)
_ENV_REFERENCE = re.compile(r"%([^%\s]+)%|\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_MISSING = object()


class SourceKind(StrEnum):
    """Where a resolved setting came from."""

    PROJECT = "project"
    ENVIRONMENT = "environment"
    EDITOR = "editor"
    USER = "user"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class SettingSource:
    """Provenance of one resolved setting.

    Attributes:
        kind: The kind of source.
        path: The file that supplied the value, or None for the
            environment, the editor and defaults.
    """

    kind: SourceKind
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class ConfigProblem:
    """An invalid or unreadable setting.

    Attributes:
        setting: Name of the setting as written in the configuration file,
            such as ``numeric.integerStrict``, or the file name when a whole
            file is unusable.
        message: Human-readable reason.
        file: The configuration file involved, or None.
    """

    setting: str
    message: str
    file: Path | None = None


@dataclass(frozen=True, slots=True)
class ManifestPrefs:
    """Manifest check preferences.

    Attributes:
        unreferenced_severity: Severity of a manifest name that resolves to
            no file.
        exempt_unlisted: Name patterns exempt from the unlisted-file check.
        exempt_unreferenced: Name patterns exempt from the unreferenced-name
            check.
    """

    unreferenced_severity: Severity = Severity.INFO
    exempt_unlisted: tuple[str, ...] = ()
    exempt_unreferenced: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """All settings for one validated location.

    Attributes:
        game_version: The Project's Game Version.
        reference_roots: Reference Root per Game Version.
        mod_roots: Absolute Mod Root directories.
        layer_specs: Ordered Layer entries, lowest first. A path entry is
            absolute; an alias entry keeps its leading ``@``.
        aliases: Layer aliases from the user-level file, keyed by name
            without the leading ``@``.
        disabled_codes: Upper-case Diagnostic codes to drop.
        numeric: Numeric strictness preferences.
        manifest: Manifest preferences.
        report_overrides: Report Project files overriding lower Layers.
        suppress_limited_notice: Suppress the limited-reference notice.
        project_file: The nearest ``soase.json``, or None.
        sources: Provenance per setting, keyed by setting name.
        problems: Invalid settings found while resolving.
        language: Name of the active localization folder.
    """

    game_version: GameVersion
    reference_roots: Mapping[GameVersion, Path]
    mod_roots: tuple[Path, ...]
    layer_specs: tuple[str, ...]
    aliases: Mapping[str, Path]
    disabled_codes: frozenset[str]
    numeric: NumericPrefs
    manifest: ManifestPrefs
    report_overrides: bool
    suppress_limited_notice: bool
    project_file: Path | None
    sources: Mapping[str, SettingSource]
    problems: tuple[ConfigProblem, ...]
    language: str = DEFAULT_LANGUAGE


@dataclass(frozen=True, slots=True)
class EffectiveSetting:
    """One line of the effective configuration report.

    Attributes:
        name: Setting name.
        value: JSON-compatible value.
        source: Where the value came from.
    """

    name: str
    value: Any
    source: SettingSource


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    """Effective configuration with provenance, for reporting.

    Attributes:
        settings: The resolved settings.
        entries: Every setting with value and source, in a stable order.
        reference_roots_found: Whether each configured Reference Root
            exists, keyed by Game Version id.
        project_files: Every ``soase.json`` above the location, nearest
            first.
        user_file: The user-level file path, whether or not it exists.
    """

    settings: ResolvedSettings
    entries: tuple[EffectiveSetting, ...]
    reference_roots_found: Mapping[str, bool]
    project_files: tuple[Path, ...] = ()
    user_file: Path | None = None


@dataclass(frozen=True, slots=True)
class _Source:
    """One configuration source with its decoded data."""

    source: SettingSource
    base: Path
    data: Mapping[str, Any]


def user_config_path() -> Path:
    """Return the platform path of the user-level configuration file.

    Returns:
        The path to ``config.json`` in the user config directory. The file
        may not exist.
    """
    return Path(platformdirs.user_config_dir(APP_NAME)) / USER_FILE_NAME


def expand_path(text: str, base: Path, env: Mapping[str, str] | None = None) -> Path:
    """Expand a configured path and make it absolute.

    Environment references and a leading ``~`` are expanded first, then a
    relative result is joined to ``base``. Unset variables stay as written.

    Args:
        text: The configured path text.
        base: Absolute directory that relative paths resolve against.
        env: Environment to read; defaults to ``os.environ``.

    Returns:
        A normalised absolute path.

    Raises:
        ValueError: If ``text`` is empty.
    """
    env = os.environ if env is None else env
    if not text.strip():
        raise ValueError("path is empty")

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or match.group(3)
        return env.get(name, match.group(0))

    expanded = _ENV_REFERENCE.sub(substitute, text.strip())
    if expanded == "~" or expanded.startswith(("~/", "~\\")):
        home = env.get("HOME") or env.get("USERPROFILE") or str(Path.home())
        expanded = home + expanded[1:]
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return Path(os.path.normpath(path))


def find_project_files(start: Path) -> tuple[Path, ...]:
    """Find every ``soase.json`` at or above a location.

    Args:
        start: A file or directory.

    Returns:
        The files found, nearest first.
    """
    directory = _start_directory(start)
    found = []
    for candidate in (directory, *directory.parents):
        file = candidate / PROJECT_FILE_NAME
        if file.is_file():
            found.append(file)
    return tuple(found)


def find_manifest_directory(start: Path) -> Path | None:
    """Find the nearest directory at or above a location holding a manifest.

    Args:
        start: A file or directory.

    Returns:
        The directory, or None when no directory above holds a ``*.manifest``
        file.
    """
    directory = _start_directory(start)
    for candidate in (directory, *directory.parents):
        if any(_manifest_files(candidate)):
            return candidate
    return None


def resolve_settings(
    path: Path,
    editor: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    user_file: Path | None = None,
) -> ResolvedSettings:
    """Resolve every setting for a file or directory.

    Args:
        path: The validated file or a directory.
        editor: Editor-supplied settings using the ``soase.json`` key names.
        env: Environment to read; defaults to ``os.environ``.
        user_file: User-level file; defaults to ``user_config_path()``.

    Returns:
        The resolved settings. Problems are collected in ``problems``.
    """
    env = os.environ if env is None else env
    user_file = user_config_path() if user_file is None else user_file
    start = _start_directory(path)
    problems: list[ConfigProblem] = []

    project_files = find_project_files(start)
    base = project_files[0].parent if project_files else start
    sources = [_load_file(file, SourceKind.PROJECT, problems) for file in project_files]
    sources.append(_environment_source(env, base))
    sources.append(_Source(SettingSource(SourceKind.EDITOR), base, dict(editor or {})))
    sources.append(_load_file(user_file, SourceKind.USER, problems))

    resolver = _Resolver([s for s in sources if s is not None], env, problems, user_file)
    return resolver.resolve(start, project_files[0] if project_files else None)


def effective_config(
    path: Path,
    editor: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    user_file: Path | None = None,
) -> EffectiveConfig:
    """Report the effective configuration with the source of each setting.

    Args:
        path: The validated file or a directory.
        editor: Editor-supplied settings using the ``soase.json`` key names.
        env: Environment to read; defaults to ``os.environ``.
        user_file: User-level file; defaults to ``user_config_path()``.

    Returns:
        The settings, a flat list of values with sources, and whether each
        Reference Root exists.
    """
    user_file = user_config_path() if user_file is None else user_file
    settings = resolve_settings(path, editor, env=env, user_file=user_file)
    default = SettingSource(SourceKind.DEFAULT)
    entries = tuple(
        EffectiveSetting(name, value, settings.sources.get(name, default))
        for name, value in _setting_values(settings)
    )
    found = {v.value: root.is_dir() for v, root in settings.reference_roots.items()}
    return EffectiveConfig(
        settings=settings,
        entries=entries,
        reference_roots_found=found,
        project_files=find_project_files(path),
        user_file=user_file,
    )


def set_reference_root(
    config_file: Path, version: GameVersion, root: str, *, user: bool = False
) -> None:
    """Write a Reference Root into a project or user-level file.

    The text is stored as given, so a relative path stays relative to the
    file. The file is created when absent and other keys are preserved.

    Args:
        config_file: The ``soase.json`` or user-level file.
        version: The Game Version the root belongs to.
        root: The path text to store.
        user: Write to ``defaultReferenceRoots`` instead of
            ``referenceRoots``.

    Raises:
        ValueError: If ``root`` is empty or the existing file is not a JSON
            object.
        OSError: If the file cannot be written.
    """
    if not root.strip():
        raise ValueError("reference root is empty")
    key = "defaultReferenceRoots" if user else "referenceRoots"
    data = _read_for_update(config_file)
    roots = data.get(key)
    if not isinstance(roots, dict):
        roots = {}
    roots[version.value] = root
    data[key] = roots
    _write_json(config_file, data)


def remove_reference_root(config_file: Path, version: GameVersion, *, user: bool = False) -> bool:
    """Remove a Reference Root from a project or user-level file.

    Args:
        config_file: The ``soase.json`` or user-level file.
        version: The Game Version whose root is removed.
        user: Remove from ``defaultReferenceRoots`` instead of
            ``referenceRoots``.

    Returns:
        True when an entry was removed.

    Raises:
        ValueError: If the existing file is not a JSON object.
        OSError: If the file cannot be written.
    """
    key = "defaultReferenceRoots" if user else "referenceRoots"
    data = _read_for_update(config_file)
    roots = data.get(key)
    if not isinstance(roots, dict):
        return False
    stale = [k for k in roots if parse_game_version(str(k)) is version]
    for k in stale:
        del roots[k]
    if stale:
        _write_json(config_file, data)
    return bool(stale)


def add_layer(config_file: Path, layer: str, index: int | None = None) -> None:
    """Add a Layer to the ordered ``layers`` list of a file.

    An entry already present (same text) is moved instead of duplicated.

    Args:
        config_file: The ``soase.json`` to edit.
        layer: A path or ``@alias`` entry.
        index: Position in the list, lowest Layer first; None appends.

    Raises:
        ValueError: If ``layer`` is empty or the existing file is not a JSON
            object.
        OSError: If the file cannot be written.
    """
    if not layer.strip():
        raise ValueError("layer is empty")
    data = _read_for_update(config_file)
    layers = [x for x in _layer_list(data) if x != layer]
    layers.insert(len(layers) if index is None else index, layer)
    data["layers"] = layers
    _write_json(config_file, data)


def remove_layer(config_file: Path, layer: str) -> bool:
    """Remove a Layer from the ``layers`` list of a file.

    Args:
        config_file: The ``soase.json`` to edit.
        layer: The entry text to remove.

    Returns:
        True when the entry was present.

    Raises:
        ValueError: If the existing file is not a JSON object.
        OSError: If the file cannot be written.
    """
    data = _read_for_update(config_file)
    layers = _layer_list(data)
    if layer not in layers:
        return False
    data["layers"] = [x for x in layers if x != layer]
    _write_json(config_file, data)
    return True


def set_layers(config_file: Path, layers: list[str]) -> None:
    """Replace the ordered ``layers`` list of a file.

    Args:
        config_file: The ``soase.json`` to edit.
        layers: The new entries, lowest Layer first.

    Raises:
        ValueError: If an entry is empty or the existing file is not a JSON
            object.
        OSError: If the file cannot be written.
    """
    if any(not x.strip() for x in layers):
        raise ValueError("layer is empty")
    data = _read_for_update(config_file)
    data["layers"] = list(layers)
    _write_json(config_file, data)


def set_alias(user_file: Path, name: str, layer_path: str) -> None:
    """Write a Layer alias into the user-level file.

    Args:
        user_file: The user-level file.
        name: Alias name, with or without a leading ``@``.
        layer_path: The path text to store.

    Raises:
        ValueError: If the name or path is empty, or the existing file is not
            a JSON object.
        OSError: If the file cannot be written.
    """
    key = name.removeprefix(ALIAS_PREFIX)
    if not key.strip() or not layer_path.strip():
        raise ValueError("alias name and path must not be empty")
    data = _read_for_update(user_file)
    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        aliases = {}
    aliases[key] = layer_path
    data["aliases"] = aliases
    _write_json(user_file, data)


class _Resolver:
    """Resolve each setting across an ordered list of sources."""

    def __init__(
        self,
        sources: list[_Source],
        env: Mapping[str, str],
        problems: list[ConfigProblem],
        user_file: Path,
    ) -> None:
        """Store the sources and shared problem list.

        Args:
            sources: Sources from highest to lowest precedence.
            env: Environment used for path expansion.
            problems: List that collects problems.
            user_file: The user-level file, for alias resolution.
        """
        self._sources = sources
        self._env = env
        self._problems = problems
        self._user_file = user_file
        self._reported: set[tuple[str, Path | None]] = set()
        self._provenance: dict[str, SettingSource] = {}

    def resolve(self, start: Path, project_file: Path | None) -> ResolvedSettings:
        """Resolve all settings.

        Args:
            start: The start directory.
            project_file: The nearest ``soase.json``, or None.

        Returns:
            The resolved settings.
        """
        game_version = self._setting(
            "gameVersion", ("gameVersion",), self._parse_version, DEFAULT_REBELLION
        )
        roots = self._reference_roots()
        mod_roots = self._setting(
            "modRoots",
            ("modRoots",),
            self._parse_paths,
            self._default_mod_roots(start, project_file),
        )
        layers = self._setting("layers", ("layers",), self._parse_layers, ())
        disabled = self._setting(
            "disabledCodes", ("disabledCodes",), self._parse_codes, frozenset()
        )
        numeric = NumericPrefs(
            integer_strict=self._setting(
                "numeric.integerStrict", ("numeric", "integerStrict"), _parse_bool, False
            ),
            decimal_allow_integer=self._setting(
                "numeric.decimalAllowInteger",
                ("numeric", "decimalAllowInteger"),
                _parse_bool,
                True,
            ),
        )
        manifest = ManifestPrefs(
            unreferenced_severity=self._setting(
                "manifest.unreferencedSeverity",
                ("manifest", "unreferencedSeverity"),
                _parse_severity,
                Severity.INFO,
            ),
            exempt_unlisted=self._setting(
                "manifest.exemptUnlisted",
                ("manifest", "exemptUnlisted"),
                _parse_strings,
                (),
            ),
            exempt_unreferenced=self._setting(
                "manifest.exemptUnreferenced",
                ("manifest", "exemptUnreferenced"),
                _parse_strings,
                (),
            ),
        )
        report_overrides = self._setting(
            "reportOverrides", ("reportOverrides",), _parse_bool, False
        )
        suppress = self._setting(
            "suppressLimitedReferenceNotice",
            ("suppressLimitedReferenceNotice",),
            _parse_bool,
            False,
        )
        language = self._setting("language", ("language",), _parse_language, DEFAULT_LANGUAGE)
        return ResolvedSettings(
            game_version=game_version,
            reference_roots=roots,
            mod_roots=mod_roots,
            layer_specs=layers,
            aliases=self._aliases(),
            disabled_codes=disabled,
            numeric=numeric,
            manifest=manifest,
            report_overrides=report_overrides,
            suppress_limited_notice=suppress,
            project_file=project_file,
            sources=dict(self._provenance),
            problems=tuple(self._problems),
            language=language,
        )

    def _problem(self, setting: str, message: str, file: Path | None) -> None:
        """Record a problem once per setting and file.

        Args:
            setting: Setting name.
            message: Reason.
            file: File involved, or None.
        """
        if (setting, file) not in self._reported:
            self._reported.add((setting, file))
            self._problems.append(ConfigProblem(setting, message, file))

    def _setting[T](
        self,
        name: str,
        json_path: tuple[str, ...],
        parse: Callable[[Any, _Source], T],
        default: T,
    ) -> T:
        """Resolve one setting from the first source that defines it.

        Args:
            name: Setting name used for provenance and problems.
            json_path: Key path inside a source.
            parse: Converts the raw value; raises ValueError when invalid.
            default: Value used when no source defines the setting or the
                chosen value is invalid.

        Returns:
            The resolved value.
        """
        for src in self._sources:
            try:
                raw = _lookup(src.data, json_path)
            except ValueError as error:
                self._problem(".".join(json_path[:-1]), str(error), src.source.path)
                self._provenance[name] = SettingSource(SourceKind.DEFAULT)
                return default
            if raw is _MISSING:
                continue
            try:
                value = parse(raw, src)
            except ValueError as error:
                self._problem(name, str(error), src.source.path)
                self._provenance[name] = SettingSource(SourceKind.DEFAULT)
                return default
            self._provenance[name] = src.source
            return value
        self._provenance[name] = SettingSource(SourceKind.DEFAULT)
        return default

    def _parse_version(self, raw: Any, src: _Source) -> GameVersion:
        """Parse a Game Version name.

        Args:
            raw: Decoded value.
            src: The source it came from.

        Returns:
            The Game Version.

        Raises:
            ValueError: If the value is not a known version name.
        """
        version = parse_game_version(raw) if isinstance(raw, str) else None
        if version is None:
            raise ValueError(f"unknown game version {raw!r}")
        return version

    def _parse_paths(self, raw: Any, src: _Source) -> tuple[Path, ...]:
        """Parse a list of paths.

        Args:
            raw: Decoded value.
            src: The source it came from.

        Returns:
            Absolute paths.

        Raises:
            ValueError: If the value is not a list of non-empty strings.
        """
        return tuple(expand_path(text, src.base, self._env) for text in _string_list(raw))

    def _parse_layers(self, raw: Any, src: _Source) -> tuple[str, ...]:
        """Parse the Layer list, expanding paths and keeping aliases.

        Args:
            raw: Decoded value.
            src: The source it came from.

        Returns:
            Absolute path strings and ``@alias`` entries.

        Raises:
            ValueError: If the value is not a list of non-empty strings.
        """
        return tuple(
            text if text.startswith(ALIAS_PREFIX) else str(expand_path(text, src.base, self._env))
            for text in _string_list(raw)
        )

    def _parse_codes(self, raw: Any, src: _Source) -> frozenset[str]:
        """Parse the disabled code list.

        Args:
            raw: Decoded value.
            src: The source it came from.

        Returns:
            Upper-case codes.

        Raises:
            ValueError: If the value is not a list of non-empty strings.
        """
        return frozenset(text.strip().upper() for text in _string_list(raw))

    def _reference_roots(self) -> dict[GameVersion, Path]:
        """Resolve the Reference Root of each Game Version.

        Returns:
            Roots for the versions that have one configured.
        """
        roots: dict[GameVersion, Path] = {}
        for version in GameVersion:
            name = f"referenceRoots.{version.value}"
            for src in self._sources:
                key = (
                    "defaultReferenceRoots"
                    if src.source.kind is SourceKind.USER
                    else "referenceRoots"
                )
                raw = self._root_entry(src, key, version)
                if raw is _MISSING:
                    continue
                try:
                    if not isinstance(raw, str):
                        raise ValueError(f"reference root for {version.value} must be a string")
                    roots[version] = expand_path(raw, src.base, self._env)
                    self._provenance[name] = src.source
                except ValueError as error:
                    self._problem(name, str(error), src.source.path)
                break
        return roots

    def _root_entry(self, src: _Source, key: str, version: GameVersion) -> Any:
        """Find the entry for a version in a source's root table.

        Args:
            src: The source.
            key: ``referenceRoots`` or ``defaultReferenceRoots``.
            version: The Game Version.

        Returns:
            The raw value, or the missing marker.
        """
        table = src.data.get(key, _MISSING)
        if table is _MISSING:
            return _MISSING
        if not isinstance(table, dict):
            self._problem(key, f"{key} must be an object", src.source.path)
            return _MISSING
        for name, value in table.items():
            parsed = parse_game_version(str(name))
            if parsed is None:
                self._problem(f"{key}.{name}", f"unknown game version {name!r}", src.source.path)
            elif parsed is version:
                return value
        return _MISSING

    def _aliases(self) -> dict[str, Path]:
        """Read the Layer aliases from the user-level file.

        Returns:
            Alias paths keyed by name without the leading ``@``.
        """
        for src in self._sources:
            if src.source.kind is not SourceKind.USER or "aliases" not in src.data:
                continue
            self._provenance["aliases"] = src.source
            table = src.data["aliases"]
            if not isinstance(table, dict):
                self._problem("aliases", "aliases must be an object", src.source.path)
                return {}
            aliases: dict[str, Path] = {}
            for name, value in table.items():
                key = str(name).removeprefix(ALIAS_PREFIX)
                try:
                    if not isinstance(value, str):
                        raise ValueError(f"alias {name!r} must map to a path string")
                    aliases[key] = expand_path(value, src.base, self._env)
                except ValueError as error:
                    self._problem(f"aliases.{name}", str(error), src.source.path)
            return aliases
        self._provenance["aliases"] = SettingSource(SourceKind.DEFAULT)
        return {}

    def _default_mod_roots(self, start: Path, project_file: Path | None) -> tuple[Path, ...]:
        """Compute the default Mod Roots.

        Args:
            start: The start directory.
            project_file: The nearest ``soase.json``, or None.

        Returns:
            The nearest directory holding a manifest, else the directory of
            the nearest ``soase.json``, else an empty tuple.
        """
        manifest_dir = find_manifest_directory(start)
        if manifest_dir is not None:
            return (manifest_dir,)
        if project_file is not None:
            return (project_file.parent,)
        return ()


def _parse_bool(raw: Any, src: _Source) -> bool:
    """Parse a boolean setting.

    Args:
        raw: Decoded value.
        src: The source it came from.

    Returns:
        The boolean.

    Raises:
        ValueError: If the value is not a JSON boolean.
    """
    if not isinstance(raw, bool):
        raise ValueError("must be true or false")
    return raw


def _parse_language(raw: Any, src: _Source) -> str:
    """Parse a localization folder name.

    Args:
        raw: Decoded value.
        src: The source it came from.

    Returns:
        The name without surrounding whitespace.

    Raises:
        ValueError: If the value is not a plain folder name.
    """
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or "/" in text or "\\" in text or text.startswith("."):
        raise ValueError("must be a localization folder name such as en")
    return text


def _parse_severity(raw: Any, src: _Source) -> Severity:
    """Parse a manifest severity.

    Args:
        raw: Decoded value.
        src: The source it came from.

    Returns:
        The severity.

    Raises:
        ValueError: If the value is not error, warning or info.
    """
    for severity in _MANIFEST_SEVERITIES:
        if isinstance(raw, str) and raw.strip().lower() == severity.value:
            return severity
    allowed = ", ".join(s.value for s in _MANIFEST_SEVERITIES)
    raise ValueError(f"severity must be one of {allowed}")


def _parse_strings(raw: Any, src: _Source) -> tuple[str, ...]:
    """Parse a list of strings.

    Args:
        raw: Decoded value.
        src: The source it came from.

    Returns:
        The strings.

    Raises:
        ValueError: If the value is not a list of non-empty strings.
    """
    return tuple(_string_list(raw))


def _string_list(raw: Any) -> list[str]:
    """Check a decoded value is a list of non-empty strings.

    Args:
        raw: Decoded value.

    Returns:
        The list.

    Raises:
        ValueError: If the value is not a list of non-empty strings.
    """
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        raise ValueError("must be a list of non-empty strings")
    return raw


def _lookup(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    """Walk a key path in decoded data.

    Args:
        data: Decoded object.
        path: Keys to follow.

    Returns:
        The value, or the missing marker when a key is absent.

    Raises:
        ValueError: If an intermediate value is not an object.
    """
    current: Any = data
    for index, key in enumerate(path):
        if not isinstance(current, Mapping):
            raise ValueError(f"{'.'.join(path[:index])} must be an object")
        if key not in current:
            return _MISSING
        current = current[key]
    return current


def _start_directory(path: Path) -> Path:
    """Return the absolute directory to search from.

    Args:
        path: A file or directory.

    Returns:
        The directory itself, or the parent of a file.
    """
    absolute = Path(os.path.abspath(path))
    return absolute if absolute.is_dir() else absolute.parent


def _manifest_files(directory: Path) -> Iterator[str]:
    """List manifest file names in a directory.

    Args:
        directory: Directory to scan.

    Yields:
        Names ending in ``.manifest``, compared case-insensitively.
    """
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.lower().endswith(_MANIFEST_SUFFIX) and entry.is_file():
                    yield entry.name
    except OSError:
        return


def _load_file(file: Path, kind: SourceKind, problems: list[ConfigProblem]) -> _Source | None:
    """Read a configuration file as a source.

    Args:
        file: The file to read.
        kind: The source kind to record.
        problems: List that receives a problem when the file is unusable.

    Returns:
        The source, or None when the file is absent or unusable.
    """
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        problems.append(ConfigProblem(file.name, f"cannot read file: {error}", file))
        return None
    if not isinstance(data, dict):
        problems.append(ConfigProblem(file.name, "file must contain a JSON object", file))
        return None
    return _Source(SettingSource(kind, file), file.parent, data)


def _environment_source(env: Mapping[str, str], base: Path) -> _Source:
    """Build a source from environment variables.

    Args:
        env: The environment.
        base: Directory that relative paths resolve against.

    Returns:
        A source using the ``soase.json`` key names.
    """
    data: dict[str, Any] = {}
    if env.get(ENV_GAME_VERSION):
        data["gameVersion"] = env[ENV_GAME_VERSION]
    if env.get(ENV_LANGUAGE):
        data["language"] = env[ENV_LANGUAGE]
    roots = {
        version.value: env[ENV_REFERENCE_ROOT_PREFIX + version.name]
        for version in GameVersion
        if env.get(ENV_REFERENCE_ROOT_PREFIX + version.name)
    }
    if roots:
        data["referenceRoots"] = roots
    return _Source(SettingSource(SourceKind.ENVIRONMENT), base, data)


def _setting_values(settings: ResolvedSettings) -> list[tuple[str, Any]]:
    """List settings as JSON-compatible name and value pairs.

    Args:
        settings: The resolved settings.

    Returns:
        Pairs in a stable order.
    """
    values: list[tuple[str, Any]] = [
        ("gameVersion", settings.game_version.value),
        ("language", settings.language),
    ]
    values.extend(
        (f"referenceRoots.{v.value}", str(settings.reference_roots[v]))
        for v in GameVersion
        if v in settings.reference_roots
    )
    values.extend(
        [
            ("modRoots", [str(p) for p in settings.mod_roots]),
            ("layers", list(settings.layer_specs)),
            ("aliases", {k: str(v) for k, v in settings.aliases.items()}),
            ("disabledCodes", sorted(settings.disabled_codes)),
            ("numeric.integerStrict", settings.numeric.integer_strict),
            ("numeric.decimalAllowInteger", settings.numeric.decimal_allow_integer),
            ("manifest.unreferencedSeverity", settings.manifest.unreferenced_severity.value),
            ("manifest.exemptUnlisted", list(settings.manifest.exempt_unlisted)),
            ("manifest.exemptUnreferenced", list(settings.manifest.exempt_unreferenced)),
            ("reportOverrides", settings.report_overrides),
            ("suppressLimitedReferenceNotice", settings.suppress_limited_notice),
        ]
    )
    return values


def _layer_list(data: dict[str, Any]) -> list[str]:
    """Read the ``layers`` list from file data.

    Args:
        data: Decoded file content.

    Returns:
        The entries that are strings; empty when absent or malformed.
    """
    layers = data.get("layers")
    if not isinstance(layers, list):
        return []
    return [x for x in layers if isinstance(x, str)]


def _read_for_update(file: Path) -> dict[str, Any]:
    """Read a configuration file for modification.

    Args:
        file: The file to read.

    Returns:
        The decoded object, or an empty dict when the file is absent.

    Raises:
        ValueError: If the file is not valid JSON or not an object.
    """
    if not file.exists():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise ValueError(f"{file.name} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{file.name} must contain a JSON object")
    return data


def _write_json(file: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically.

    Args:
        file: Destination file; parent directories are created.
        data: Content to write.

    Raises:
        OSError: If the file cannot be written.
    """
    file.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(dir=file.parent, prefix=file.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, file)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


__all__ = [
    "ALIAS_PREFIX",
    "DEFAULT_LANGUAGE",
    "ENV_GAME_VERSION",
    "ENV_LANGUAGE",
    "ENV_REFERENCE_ROOT_PREFIX",
    "PROJECT_FILE_NAME",
    "ConfigProblem",
    "EffectiveConfig",
    "EffectiveSetting",
    "ManifestPrefs",
    "NumericPrefs",
    "ResolvedSettings",
    "SettingSource",
    "SourceKind",
    "add_layer",
    "effective_config",
    "expand_path",
    "find_manifest_directory",
    "find_project_files",
    "remove_layer",
    "remove_reference_root",
    "resolve_settings",
    "set_alias",
    "set_layers",
    "set_reference_root",
    "user_config_path",
]
