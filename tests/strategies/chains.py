"""Hypothesis strategies for Layers and Chains on the in-memory file system.

``chains()`` generates a ``GenChain``: an ``InMemoryFileSystem`` populated with
the files of several Layers, the ``Layer`` objects, the matching ``Chain`` and
the casefolded relative paths each Layer index must contain. File stems come
from a small pool so names overlap between Layers, and directory and file
names vary in case. Layers include hidden and version control directories that
indexing must skip. Chains are complete or carry ``missing`` and ``unusable``
Layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hypothesis import strategies as st

from soase_validator.engine.chain import Chain, ChainProblem, Layer, LayerStatus
from soase_validator.engine.diagnostics import C020
from soase_validator.engine.refindex import VCS_DIRECTORIES, InMemoryFileSystem

LAYER_ROOT = Path("synthetic-layers")
"""Relative parent of every generated Layer directory."""

STEMS = ("alpha", "beta", "gamma", "delta")
"""Small pool of file stems so Layers share names."""

DIRECTORY_EXTENSIONS = {
    "Sound": ".ogg",
    "Mesh": ".mesh",
    "Particle": ".particle",
    "Textures": ".dds",
    "GameInfo": ".entity",
    "String": ".str",
    "Galaxy": ".galaxy",
    "Window": ".brushes",
    "Localizations": ".ogg",
}
"""Indexed game data directory and a matching file extension."""

HIDDEN_DIRECTORIES = (".hidden", ".cache", ".vscode")
_VCS_NAMES = tuple(sorted(VCS_DIRECTORIES))
_UNINDEXED_DIRECTORIES = ("Notes", "Backup", "Docs")


@dataclass(frozen=True, slots=True)
class GenLayer:
    """A generated Layer and its files.

    Attributes:
        layer: The Layer, rooted below ``LAYER_ROOT``.
        files: Relative ``/`` separated paths of every file added to the
            file system, in their generated casing.
        expected_keys: Casefolded relative paths a Layer index must hold.
    """

    layer: Layer
    files: tuple[str, ...]
    expected_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class GenChain:
    """A generated Chain on an in-memory file system.

    Attributes:
        fs: The file system holding every Layer's files.
        layers: Generated Layers, lowest first, the Project last.
        chain: The Chain over the Layers' ``Layer`` objects.
    """

    fs: InMemoryFileSystem
    layers: tuple[GenLayer, ...]
    chain: Chain


def vary_case(name: str, mode: str) -> str:
    """Apply a case transformation to a name.

    Args:
        name: The name.
        mode: ``keep``, ``lower``, ``upper`` or ``title``.

    Returns:
        The transformed name.
    """
    match mode:
        case "lower":
            return name.lower()
        case "upper":
            return name.upper()
        case "title":
            return name.title()
        case _:
            return name


case_modes = st.sampled_from(("keep", "lower", "upper", "title"))


def is_indexed(relpath: str) -> bool:
    """Tell whether the index must contain a generated file.

    Args:
        relpath: Relative ``/`` separated path.

    Returns:
        True for a root file, or a file below a game data directory with no
        hidden or VCS directory on the way.
    """
    parts = relpath.split("/")
    if len(parts) == 1:
        return True
    folders = {name.casefold() for name in DIRECTORY_EXTENSIONS}
    return parts[0].casefold() in folders and not any(
        p.startswith(".") or p.casefold() in VCS_DIRECTORIES for p in parts[:-1]
    )


@st.composite
def _indexed_file(draw: st.DrawFn) -> str:
    directory = draw(st.sampled_from(sorted(DIRECTORY_EXTENSIONS)))
    stem = draw(st.sampled_from(STEMS))
    extension = DIRECTORY_EXTENSIONS[directory]
    return (
        f"{vary_case(directory, draw(case_modes))}/{vary_case(stem + extension, draw(case_modes))}"
    )


@st.composite
def _skipped_file(draw: st.DrawFn) -> str:
    """Draw a file inside a hidden, VCS or non-game directory."""
    stem = draw(st.sampled_from(STEMS))
    name = vary_case(stem + ".ogg", draw(case_modes))
    kind = draw(st.sampled_from(("hidden", "vcs", "other", "nested")))
    directory = draw(st.sampled_from(sorted(DIRECTORY_EXTENSIONS)))
    if kind == "hidden":
        return f"{directory}/{draw(st.sampled_from(HIDDEN_DIRECTORIES))}/{name}"
    if kind == "vcs":
        vcs = vary_case(draw(st.sampled_from(_VCS_NAMES)), draw(case_modes))
        return f"{vary_case(directory, draw(case_modes))}/{vcs}/{name}"
    if kind == "nested":
        return f"{directory}/{draw(st.sampled_from(sorted(DIRECTORY_EXTENSIONS)))}/.git/{name}"
    return f"{draw(st.sampled_from(_UNINDEXED_DIRECTORIES))}/{name}"


@st.composite
def _root_file(draw: st.DrawFn) -> str:
    stem = draw(st.sampled_from(STEMS))
    suffix = draw(st.sampled_from((".manifest", ".txt", ".entity")))
    return vary_case(stem + suffix, draw(case_modes))


@st.composite
def layer_files(draw: st.DrawFn, *, game_data: bool = True) -> tuple[str, ...]:
    """Draw the relative file paths of one Layer.

    Args:
        draw: Hypothesis draw function.
        game_data: When False only root files are drawn, so the Layer holds
            no game data directory.

    Returns:
        Paths with no two that differ only in case.
    """
    paths = list(draw(st.lists(_root_file(), max_size=3)))
    if game_data:
        paths += draw(st.lists(_indexed_file(), min_size=1, max_size=8))
        paths += draw(st.lists(_skipped_file(), max_size=4))
    unique: dict[str, str] = {}
    for path in paths:
        unique.setdefault(path.casefold(), path)
    return tuple(unique.values())


@st.composite
def _gen_layer(draw: st.DrawFn, index: int, kind: str, status: LayerStatus) -> GenLayer:
    files: tuple[str, ...] = ()
    if status == "ok":
        files = draw(layer_files())
    elif status == "unusable":
        files = draw(layer_files(game_data=False))
    name = f"layer{index}"
    layer = Layer(name, LAYER_ROOT / name, kind, status)  # type: ignore[arg-type]
    keys = frozenset(f.casefold() for f in files if is_indexed(f))
    return GenLayer(layer, files, keys)


@st.composite
def chains(draw: st.DrawFn, *, complete: bool | None = None) -> GenChain:
    """Draw a Chain with its Layers on an in-memory file system.

    The Project is the last Layer and is always ``ok``. A lower Layer may be
    the game Layer (first, ``ok`` or ``unusable``) and the others are mod
    Layers (``ok`` or ``missing``).

    Args:
        draw: Hypothesis draw function.
        complete: True to draw only complete Chains, False only incomplete
            ones, None for either.

    Returns:
        The generated Chain.
    """
    has_game = draw(st.booleans())
    mods = draw(st.integers(min_value=0, max_value=3))
    want_complete = draw(st.booleans()) if complete is None else complete
    kinds = (["game"] if has_game else []) + ["mod"] * mods + ["project"]
    lower = len(kinds) - 1
    if not want_complete and lower == 0:
        kinds.insert(0, "mod")
        lower = 1
    broken = set(
        draw(st.sets(st.integers(0, lower - 1), min_size=1, max_size=lower))
        if not want_complete
        else ()
    )
    layers: list[GenLayer] = []
    for position, kind in enumerate(kinds):
        status: LayerStatus = "ok"
        if position in broken:
            status = "unusable" if kind == "game" and draw(st.booleans()) else "missing"
        layers.append(draw(_gen_layer(position, kind, status)))
    fs = InMemoryFileSystem()
    for gen in layers:
        for relpath in gen.files:
            fs.add_file(gen.layer.path.joinpath(*relpath.split("/")), size=len(relpath))
    problems = tuple(
        ChainProblem(C020, f"Layer {g.layer.name} is {g.layer.status}", g.layer.path)
        for g in layers
        if g.layer.status != "ok"
    )
    chain = Chain(
        tuple(g.layer for g in layers),
        all(g.layer.status == "ok" for g in layers if g.layer.kind != "project"),
        problems,
    )
    return GenChain(fs, tuple(layers), chain)
