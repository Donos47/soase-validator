"""Per-Layer file index and file-reference resolution.

A :class:`LayerIndex` records the files of one Layer: the files directly in the
Layer root plus every file below the directories listed in
``GAME_DATA_DIRECTORIES``. Hidden directories and version control directories
are never entered. File-reference kinds resolve by existence in that file map
according to ``FILE_REFERENCE_RULES``; their content is never read. Named
kinds are filled in by :mod:`nameindex`.

The file system is reached only through the :class:`FileSystem` protocol, so
the same code runs against the real disk and an in-memory tree.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Any, Protocol

from soase_validator.engine.chain import GAME_DATA_DIRECTORIES, Layer
from soase_validator.engine.config import DEFAULT_LANGUAGE
from soase_validator.engine.parser import read_text_file

VCS_DIRECTORIES = frozenset({".git", ".svn", ".hg"})

_GAME_DATA_FOLDERS = frozenset(name.casefold() for name in GAME_DATA_DIRECTORIES)


class RefKind(StrEnum):
    """Kinds of name the Reference Index resolves.

    Each value equals the Definition validation type that carries it.
    """

    ENTITY = "Entity"
    BRUSH = "Brush"
    STRING_INFO = "StringInfo"
    SOUND = "Sound"
    SOUND_FILE = "SoundFile"
    MESH = "Mesh"
    PARTICLE = "Particle"
    TEXTURE = "Texture"
    EXPLOSION = "Explosion"
    GALAXY_DESIGN = "GalaxyDesign"
    GALAXY_TEMPLATE = "GalaxyTemplate"
    ORBIT_BODY_TYPE = "GalaxyOrbitBodyType"


@dataclass(frozen=True, slots=True)
class FsEntry:
    """A directory listing entry.

    Attributes:
        name: The entry name.
        is_dir: True for a directory.
    """

    name: str
    is_dir: bool


@dataclass(frozen=True, slots=True)
class FileStat:
    """The stat fields that feed the signature.

    Attributes:
        size: Size in bytes.
        mtime_ns: Modification time in nanoseconds.
    """

    size: int
    mtime_ns: int


class FileSystem(Protocol):
    """The file system operations the index needs."""

    def list_dir(self, path: Path) -> list[FsEntry]:
        """List a directory.

        Args:
            path: The directory.

        Returns:
            Its entries, or an empty list when it cannot be read.
        """
        ...

    def stat(self, path: Path) -> FileStat | None:
        """Stat a file.

        Args:
            path: The file.

        Returns:
            Its size and modification time, or None when it is not a
            readable file.
        """
        ...

    def read_text(self, path: Path) -> str | None:
        """Read a file as text.

        Args:
            path: The file.

        Returns:
            The decoded text, or None when the file cannot be read.
        """
        ...


class RealFileSystem:
    """:class:`FileSystem` backed by the operating system."""

    def list_dir(self, path: Path) -> list[FsEntry]:
        """List a directory.

        Args:
            path: The directory.

        Returns:
            Its entries, or an empty list on any ``OSError``.
        """
        entries: list[FsEntry] = []
        try:
            for child in path.iterdir():
                try:
                    entries.append(FsEntry(child.name, child.is_dir()))
                except OSError:
                    continue
        except OSError:
            return []
        return entries

    def stat(self, path: Path) -> FileStat | None:
        """Stat a file.

        Args:
            path: The file.

        Returns:
            Its size and modification time, or None when it is not a file or
            cannot be read.
        """
        try:
            if not path.is_file():
                return None
            info = path.stat()
        except OSError:
            return None
        return FileStat(info.st_size, info.st_mtime_ns)

    def read_text(self, path: Path) -> str | None:
        """Read a file as text.

        Args:
            path: The file.

        Returns:
            The decoded text, or None on any ``OSError``.
        """
        try:
            return read_text_file(path)
        except OSError:
            return None


class InMemoryFileSystem:
    """:class:`FileSystem` over a dictionary of files.

    Directories exist implicitly as the parents of files.
    """

    def __init__(self) -> None:
        """Create an empty file system."""
        self._files: dict[Path, FileStat] = {}
        self._texts: dict[Path, str] = {}

    def add_file(
        self, path: Path, size: int = 0, mtime_ns: int = 0, *, text: str | None = None
    ) -> None:
        """Add or replace a file.

        Args:
            path: The file path.
            size: Size in bytes.
            mtime_ns: Modification time in nanoseconds.
            text: Content returned by :meth:`read_text`; None leaves the
                file unreadable.
        """
        self._files[path] = FileStat(size, mtime_ns)
        if text is None:
            self._texts.pop(path, None)
        else:
            self._texts[path] = text

    def remove_file(self, path: Path) -> None:
        """Remove a file if present.

        Args:
            path: The file path.
        """
        self._files.pop(path, None)
        self._texts.pop(path, None)

    def read_text(self, path: Path) -> str | None:
        """Read a file's stored text.

        Args:
            path: The file path.

        Returns:
            The text given to :meth:`add_file`, or None when there is none.
        """
        return self._texts.get(path)

    def list_dir(self, path: Path) -> list[FsEntry]:
        """List the files and implied directories directly below a path.

        Args:
            path: The directory.

        Returns:
            Its entries; empty when nothing lies below the path.
        """
        found: dict[str, bool] = {}
        depth = len(path.parts)
        for file in self._files:
            if len(file.parts) <= depth or file.parts[:depth] != path.parts:
                continue
            name = file.parts[depth]
            is_dir = len(file.parts) > depth + 1
            found[name] = found.get(name, False) or is_dir
        return [FsEntry(name, is_dir) for name, is_dir in found.items()]

    def stat(self, path: Path) -> FileStat | None:
        """Stat a file.

        Args:
            path: The file path.

        Returns:
            Its stored size and time, or None when it was not added.
        """
        return self._files.get(path)


@dataclass(frozen=True, slots=True)
class Entry:
    """A named item defined in a Layer.

    Attributes:
        name: The name in its original casing.
        kind: The kind of name.
        file: The file that defines it.
        layer_name: The name of the Layer that holds the file.
    """

    name: str
    kind: RefKind
    file: Path
    layer_name: str


@dataclass(frozen=True, slots=True)
class LayerIndex:
    """The index of one Layer.

    Attributes:
        layer: The indexed Layer.
        signature: Hash of ``(relpath, size, mtime_ns)`` of every indexed
            file.
        names: Names per kind, keyed by casefolded name.
        manifests: Parsed manifests per manifest type.
        files: Casefolded relative path (``/`` separated) to absolute path.
        stats: Casefolded relative path to ``(size, mtime_ns)``.
        language: The localization the names were read for.
    """

    layer: Layer
    signature: str
    names: Mapping[RefKind, Mapping[str, Entry]] = field(default_factory=dict)
    manifests: Mapping[str, Any] = field(default_factory=dict)
    files: Mapping[str, Path] = field(default_factory=dict)
    stats: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    language: str = DEFAULT_LANGUAGE


@dataclass(frozen=True, slots=True)
class FileReferenceRule:
    """Where a file-reference kind lives and how its names are written.

    Attributes:
        directory: Game data directory below the Layer root.
        extensions: Accepted file extensions including the dot, casefolded.
            A name without an extension resolves when a file with any of
            them exists.
        extension_in: Casefolded extensions of the referencing files whose
            names may carry a file extension, or None when they may in every
            file. For other files a name is always extended by the rule, so
            a name that spells the extension does not resolve.
        any_extension: True when a name with any extension names that exact
            file; otherwise only the rule's own extensions are recognised.
        localized: True when the directory also exists per language below
            ``Localizations``.
    """

    directory: str
    extensions: tuple[str, ...]
    extension_in: frozenset[str] | None = None
    any_extension: bool = False
    localized: bool = False


LOCALIZATIONS_DIRECTORY = "localizations"

#: The localization that backs up the configured one.
FALLBACK_LANGUAGE = "en"

FILE_REFERENCE_RULES: Mapping[RefKind, FileReferenceRule] = {
    RefKind.SOUND_FILE: FileReferenceRule("Sound", (".ogg",), localized=True),
    RefKind.MESH: FileReferenceRule("Mesh", (".mesh",), frozenset({".particle"})),
    RefKind.PARTICLE: FileReferenceRule("Particle", (".particle",)),
    RefKind.TEXTURE: FileReferenceRule("Textures", (".dds", ".tga"), any_extension=True),
}


def is_absolute_reference(name: str) -> bool:
    """Tell whether a name is an absolute or separator-bearing path.

    Args:
        name: The referenced name.

    Returns:
        True when the name has a drive letter or a path separator.
    """
    return "/" in name or "\\" in name or (len(name) > 1 and name[1] == ":" and name[0].isalpha())


def file_name_of(name: str) -> str:
    r"""Reduce a drive-letter path to its file name.

    Args:
        name: The referenced name.

    Returns:
        The text after the last ``\`` or ``/`` when the name starts with a
        drive letter followed by ``:\`` or ``:/``; otherwise the name.
    """
    if len(name) > 2 and name[0].isalpha() and name[1] == ":" and name[2] in "\\/":
        return name.replace("\\", "/").rsplit("/", 1)[-1]
    return name


def _relpath_key(root: Path, path: Path) -> str | None:
    """Return the casefolded ``/``-separated path of a file below a root.

    Args:
        root: The Layer root.
        path: The file path.

    Returns:
        The key, or None when the path is not below the root.
    """
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if not parts:
        return None
    return "/".join(parts).casefold()


def _skipped_directory(name: str) -> bool:
    """Tell whether a directory is hidden or a VCS directory.

    Args:
        name: The directory name.

    Returns:
        True when the directory is never entered.
    """
    return name.startswith(".") or name.casefold() in VCS_DIRECTORIES


def _is_indexed(key: str) -> bool:
    """Tell whether a relative path is in the scanned scope.

    Args:
        key: Casefolded ``/``-separated relative path.

    Returns:
        True for a file directly in the root or below a game data
        directory, with no hidden or VCS directory on the way.
    """
    parts = key.split("/")
    if len(parts) == 1:
        return True
    return parts[0] in _GAME_DATA_FOLDERS and not any(_skipped_directory(p) for p in parts[:-1])


def compute_signature(stats: Mapping[str, tuple[int, int]]) -> str:
    """Hash the indexed files' paths, sizes and modification times.

    Args:
        stats: Casefolded relative path to ``(size, mtime_ns)``.

    Returns:
        ``sha256:`` followed by the hex digest. Equal inputs give equal
        signatures regardless of insertion order.
    """
    digest = hashlib.sha256()
    for relpath in sorted(stats):
        size, mtime_ns = stats[relpath]
        digest.update(f"{relpath}\0{size}\0{mtime_ns}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def _scan(fs: FileSystem, root: Path) -> dict[str, Path]:
    """Collect the indexed files of a Layer.

    Args:
        fs: The file system.
        root: The Layer root.

    Returns:
        Casefolded relative path to absolute path.
    """
    found: dict[str, Path] = {}

    def walk(directory: Path) -> None:
        for entry in fs.list_dir(directory):
            child = directory / entry.name
            if entry.is_dir:
                if not _skipped_directory(entry.name):
                    walk(child)
                continue
            key = _relpath_key(root, child)
            if key is not None:
                found[key] = child

    for entry in fs.list_dir(root):
        child = root / entry.name
        if entry.is_dir:
            if entry.name.casefold() in _GAME_DATA_FOLDERS and not _skipped_directory(entry.name):
                walk(child)
        else:
            found[entry.name.casefold()] = child
    return found


def build_layer_index(layer: Layer, fs: FileSystem | None = None) -> LayerIndex:
    """Index the files of one Layer.

    Args:
        layer: The Layer; a Layer whose directory cannot be listed yields an
            empty index.
        fs: The file system; defaults to the real one.

    Returns:
        The index. Only root files and the files below the standard game data
        directories are included; hidden and VCS directories are skipped.
    """
    fs = RealFileSystem() if fs is None else fs
    files = _scan(fs, layer.path)
    stats: dict[str, tuple[int, int]] = {}
    for key, path in list(files.items()):
        info = fs.stat(path)
        if info is None:
            del files[key]
            continue
        stats[key] = (info.size, info.mtime_ns)
    return LayerIndex(layer, compute_signature(stats), files=files, stats=stats)


def update_file(index: LayerIndex, path: Path, fs: FileSystem | None = None) -> LayerIndex:
    """Refresh one file in an index.

    Args:
        index: The index to update.
        path: The absolute path of the changed, added or deleted file.
        fs: The file system; defaults to the real one.

    Returns:
        A new index equal to a full rebuild, names included, when only this
        file changed. The index is returned unchanged for a path outside the
        Layer or outside the scanned scope.
    """
    fs = RealFileSystem() if fs is None else fs
    key = _relpath_key(index.layer.path, path)
    if key is None or not _is_indexed(key):
        return index
    files = dict(index.files)
    stats = dict(index.stats)
    info = fs.stat(path)
    if info is None:
        files.pop(key, None)
        stats.pop(key, None)
    else:
        files[key] = path
        stats[key] = (info.size, info.mtime_ns)
    updated = replace(index, signature=compute_signature(stats), files=files, stats=stats)
    # nameindex imports this module, so it is imported here to avoid a cycle.
    from soase_validator.engine.nameindex import update_names

    return update_names(updated, key, index.files.get(key), fs)


def localized_prefixes(directory: str, language: str = DEFAULT_LANGUAGE) -> tuple[str, ...]:
    """List the folders a localized directory may live in, in lookup order.

    Args:
        directory: Directory name below the Layer root or a language folder.
        language: The configured language.

    Returns:
        Casefolded key prefixes ending in ``/``: the configured language,
        the fallback language, then the directory at the Layer root.
    """
    folder = directory.casefold()
    languages = dict.fromkeys((language.casefold(), FALLBACK_LANGUAGE))
    return (
        *(f"{LOCALIZATIONS_DIRECTORY}/{lang}/{folder}/" for lang in languages),
        f"{folder}/",
    )


def file_reference_keys(
    kind: RefKind | str,
    name: str,
    file_extension: str = "",
    language: str = DEFAULT_LANGUAGE,
) -> tuple[str, ...] | None:
    """Build the casefolded relative paths a file-reference name may point to.

    Args:
        kind: The reference kind.
        name: The referenced name, with or without a file extension.
        file_extension: Extension of the referencing file; selects whether
            the name may carry an extension.
        language: The configured language; used by localized kinds.

    Returns:
        The candidate keys into ``LayerIndex.files`` in lookup order (any one
        existing resolves the name), or None when the kind is not a
        file-reference kind.
    """
    try:
        rule = FILE_REFERENCE_RULES.get(RefKind(kind))
    except ValueError:
        return None
    if rule is None:
        return None
    if rule.localized:
        prefixes = localized_prefixes(rule.directory, language)
    else:
        prefixes = (f"{rule.directory.casefold()}/",)
    base = file_name_of(name).casefold()
    may_carry = rule.extension_in is None or file_extension.casefold() in rule.extension_in
    if may_carry:
        suffix = PurePath(base).suffix
        if base.endswith(rule.extensions) or (rule.any_extension and suffix):
            return tuple(prefix + base for prefix in prefixes)
    return tuple(prefix + base + extension for prefix in prefixes for extension in rule.extensions)


def find_file(
    indexes: Iterable[LayerIndex],
    kind: RefKind | str,
    name: str,
    file_extension: str = "",
    language: str = DEFAULT_LANGUAGE,
) -> Path | None:
    """Find the file a file-reference name points to.

    Args:
        indexes: Layer indexes from highest to lowest.
        kind: The reference kind.
        name: The referenced name.
        file_extension: Extension of the referencing file.
        language: The configured language.

    Returns:
        The path from the highest Layer holding the file, or None when no
        Layer has it or the kind is not a file-reference kind. Within a Layer
        the candidate keys are tried in lookup order. Existence only; the
        content is never read.
    """
    keys = file_reference_keys(kind, name, file_extension, language)
    if keys is None:
        return None
    for index in indexes:
        for key in keys:
            path = index.files.get(key)
            if path is not None:
                return path
    return None


__all__ = [
    "FALLBACK_LANGUAGE",
    "FILE_REFERENCE_RULES",
    "LOCALIZATIONS_DIRECTORY",
    "VCS_DIRECTORIES",
    "Entry",
    "FileReferenceRule",
    "FileStat",
    "FileSystem",
    "FsEntry",
    "InMemoryFileSystem",
    "LayerIndex",
    "RealFileSystem",
    "RefKind",
    "build_layer_index",
    "compute_signature",
    "file_reference_keys",
    "file_name_of",
    "find_file",
    "is_absolute_reference",
    "localized_prefixes",
    "update_file",
]
