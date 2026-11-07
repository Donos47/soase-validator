"""In-memory and on-disk cache of per-Layer indexes.

An index is cached under ``(resolved Layer path, Game Version, language)``; the
language decides which localized files define names. The
in-memory cache serves every Project in the process that shares a Layer. The
on-disk cache is one JSON file per key in the platform cache directory and
carries a schema version, so it survives restarts. A cached index is reused
only when its signature equals the signature of the Layer as it is now; any
other file is stale and is replaced.

The cache is an optimisation. A missing, unreadable, corrupt, stale or
foreign-schema file is treated as absent, and a failed write is ignored.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import platformdirs

from soase_validator.engine.chain import Layer
from soase_validator.engine.config import APP_NAME, DEFAULT_LANGUAGE
from soase_validator.engine.nameindex import index_names
from soase_validator.engine.refindex import (
    Entry,
    FileSystem,
    LayerIndex,
    RefKind,
    build_layer_index,
)
from soase_validator.engine.versions import GameVersion

SCHEMA_VERSION = 3

_CACHE_SUBDIRECTORY = "layers"

CacheKey = tuple[Path, GameVersion, str]


def default_cache_dir() -> Path:
    """Return the platform cache directory for Layer indexes.

    Returns:
        The directory; it may not exist.
    """
    return Path(platformdirs.user_cache_dir(APP_NAME)) / _CACHE_SUBDIRECTORY


def cache_key(layer: Layer, version: GameVersion, language: str = DEFAULT_LANGUAGE) -> CacheKey:
    """Build the cache key of a Layer.

    Args:
        layer: The Layer.
        version: The Game Version.
        language: The configured language.

    Returns:
        The resolved Layer path, the Game Version and the casefolded
        language.
    """
    return (layer.path.resolve(), version, language.casefold())


def _portable(path: Path, root: Path) -> str:
    """Write a path relative to a Layer root with ``/`` separators.

    Args:
        path: The path to write.
        root: The Layer root.

    Returns:
        The relative path, or the path itself when it lies outside the root.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _unportable(text: str, root: Path) -> Path:
    """Reverse :func:`_portable`.

    Args:
        text: The stored text.
        root: The Layer root.

    Returns:
        The path below the root, or the stored absolute path.
    """
    stored = Path(text)
    return stored if stored.is_absolute() else root / stored


def serialize_index(index: LayerIndex, version: GameVersion) -> dict[str, Any]:
    """Convert an index to a JSON-compatible dictionary.

    The Layer itself is not stored; the caller supplies it on load. Paths
    below the Layer root are stored relative to it.

    Args:
        index: The index.
        version: The Game Version it was built for.

    Returns:
        The dictionary.
    """
    root = index.layer.path
    return {
        "schema": SCHEMA_VERSION,
        "game_version": version.value,
        "language": index.language.casefold(),
        "layer_path": str(root.resolve()),
        "signature": index.signature,
        "files": {key: _portable(path, root) for key, path in index.files.items()},
        "stats": {key: [size, mtime] for key, (size, mtime) in index.stats.items()},
        "names": {
            kind.value: {
                key: {
                    "name": entry.name,
                    "file": _portable(entry.file, root),
                    "layer_name": entry.layer_name,
                }
                for key, entry in entries.items()
            }
            for kind, entries in index.names.items()
        },
        "manifests": dict(index.manifests),
    }


def deserialize_index(
    data: Any,
    layer: Layer,
    version: GameVersion,
    signature: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> LayerIndex | None:
    """Rebuild an index from a decoded dictionary.

    Args:
        data: The decoded JSON value.
        layer: The Layer the index is for.
        version: The expected Game Version.
        signature: The Layer's current signature. When given, a stored index
            with another signature is rejected.
        language: The expected language.

    Returns:
        The index, or None when the data has the wrong schema, Game Version,
        language, Layer path or signature, or is malformed.
    """
    try:
        if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
            return None
        if data["game_version"] != version.value or data["language"] != language.casefold():
            return None
        if data["layer_path"] != str(layer.path.resolve()):
            return None
        stored = data["signature"]
        if not isinstance(stored, str) or (signature is not None and stored != signature):
            return None
        root = layer.path
        files = {str(key): _unportable(str(text), root) for key, text in data["files"].items()}
        stats = {str(key): (int(pair[0]), int(pair[1])) for key, pair in data["stats"].items()}
        names: dict[RefKind, dict[str, Entry]] = {}
        for kind_text, entries in data["names"].items():
            kind = RefKind(kind_text)
            names[kind] = {
                str(key): Entry(
                    str(item["name"]),
                    kind,
                    _unportable(str(item["file"]), root),
                    str(item["layer_name"]),
                )
                for key, item in entries.items()
            }
        manifests = data["manifests"]
        if not isinstance(manifests, dict):
            return None
    except KeyError, TypeError, ValueError, AttributeError, IndexError:
        return None
    return LayerIndex(layer, stored, names, manifests, files, stats, language.casefold())


def _rebind(index: LayerIndex, layer: Layer) -> LayerIndex:
    """Attach a cached index to another Layer object for the same directory.

    Args:
        index: The cached index.
        layer: The Layer asking for it.

    Returns:
        The index with its Layer, paths and Layer names taken from ``layer``.
    """
    old = index.layer
    if old == layer:
        return index

    def move(path: Path) -> Path:
        try:
            return layer.path / path.relative_to(old.path)
        except ValueError:
            return path

    names = {
        kind: {
            key: replace(entry, file=move(entry.file), layer_name=layer.name)
            for key, entry in entries.items()
        }
        for kind, entries in index.names.items()
    }
    files = {key: move(path) for key, path in index.files.items()}
    return replace(index, layer=layer, names=names, files=files)


class LayerCache:
    """Two-level cache of :class:`LayerIndex` objects.

    Attributes:
        cache_dir: Directory of the JSON files, or None for memory only.
    """

    def __init__(self, cache_dir: Path | None = None, *, use_disk: bool = True) -> None:
        """Create a cache.

        Args:
            cache_dir: Directory for the JSON files; defaults to the platform
                cache directory.
            use_disk: False keeps the cache in memory only.
        """
        if use_disk:
            self.cache_dir: Path | None = default_cache_dir() if cache_dir is None else cache_dir
        else:
            self.cache_dir = None
        self._memory: dict[CacheKey, LayerIndex] = {}

    def file_for(
        self, layer: Layer, version: GameVersion, language: str = DEFAULT_LANGUAGE
    ) -> Path | None:
        """Return the on-disk file of a key.

        Args:
            layer: The Layer.
            version: The Game Version.
            language: The configured language.

        Returns:
            The JSON file path, or None when the disk cache is off.
        """
        if self.cache_dir is None:
            return None
        path, _, folded = cache_key(layer, version, language)
        digest = hashlib.sha256(f"{path}\0{version.value}\0{folded}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(
        self,
        layer: Layer,
        version: GameVersion,
        signature: str,
        language: str = DEFAULT_LANGUAGE,
    ) -> LayerIndex | None:
        """Look up an index whose signature matches the Layer as it is now.

        A stale or unreadable disk file is deleted when possible.

        Args:
            layer: The Layer.
            version: The Game Version.
            signature: The Layer's current signature.
            language: The configured language.

        Returns:
            The cached index bound to ``layer``, or None.
        """
        key = cache_key(layer, version, language)
        held = self._memory.get(key)
        if held is not None:
            if held.signature == signature:
                return _rebind(held, layer)
            del self._memory[key]
        loaded = self._read(layer, version, signature, language)
        if loaded is not None:
            self._memory[key] = loaded
        return loaded

    def put(self, index: LayerIndex, version: GameVersion) -> None:
        """Store an index in memory and, when possible, on disk.

        Args:
            index: The index.
            version: The Game Version it was built for.
        """
        self._memory[cache_key(index.layer, version, index.language)] = index
        self._write(index, version)

    def get_or_build(
        self,
        layer: Layer,
        version: GameVersion,
        fs: FileSystem | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> LayerIndex:
        """Return the current index of a Layer, reusing a valid cached one.

        The Layer is scanned and its signature computed. A cached index is
        reused only when its signature matches; otherwise the defining files
        are read for their names and the fresh index replaces it.

        Args:
            layer: The Layer.
            version: The Game Version.
            fs: The file system; defaults to the real one.
            language: The configured language.

        Returns:
            The index.
        """
        scanned = build_layer_index(layer, fs)
        cached = self.get(layer, version, scanned.signature, language)
        if cached is not None:
            return cached
        fresh = index_names(scanned, fs, language.casefold())
        self.put(fresh, version)
        return fresh

    def clear_memory(self) -> None:
        """Drop every in-memory entry; disk files stay."""
        self._memory.clear()

    def _read(
        self, layer: Layer, version: GameVersion, signature: str, language: str
    ) -> LayerIndex | None:
        """Load a valid index from disk.

        Args:
            layer: The Layer.
            version: The Game Version.
            signature: The Layer's current signature.
            language: The configured language.

        Returns:
            The index, or None when the file is absent, unreadable, corrupt,
            of another schema or stale. An invalid file is removed.
        """
        file = self.file_for(layer, version, language)
        if file is None:
            return None
        try:
            text = file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError, UnicodeDecodeError:
            self._discard(file)
            return None
        try:
            data = json.loads(text)
        except ValueError:
            self._discard(file)
            return None
        index = deserialize_index(data, layer, version, signature, language)
        if index is None:
            self._discard(file)
        return index

    def _write(self, index: LayerIndex, version: GameVersion) -> None:
        """Write an index to disk, ignoring failures.

        An index whose manifests are not JSON-compatible is not written.

        Args:
            index: The index.
            version: The Game Version.
        """
        file = self.file_for(index.layer, version, index.language)
        if file is None:
            return
        temp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
        try:
            text = json.dumps(serialize_index(index, version), separators=(",", ":"))
            file.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, file)
        except OSError, TypeError, ValueError:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)

    @staticmethod
    def _discard(file: Path) -> None:
        """Delete an invalid cache file, ignoring failures.

        Args:
            file: The file.
        """
        with contextlib.suppress(OSError):
            file.unlink(missing_ok=True)


__all__ = [
    "SCHEMA_VERSION",
    "CacheKey",
    "LayerCache",
    "cache_key",
    "default_cache_dir",
    "deserialize_index",
    "serialize_index",
]
