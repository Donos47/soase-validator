"""Unit tests for the in-memory and on-disk Layer index cache."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from soase_validator.engine import layercache
from soase_validator.engine.chain import Layer
from soase_validator.engine.layercache import (
    SCHEMA_VERSION,
    LayerCache,
    default_cache_dir,
    deserialize_index,
    serialize_index,
)
from soase_validator.engine.refindex import (
    Entry,
    InMemoryFileSystem,
    LayerIndex,
    RefKind,
    build_layer_index,
)
from soase_validator.engine.versions import GameVersion

VERSION = GameVersion.REBELLION_194


def _layer(root: Path, name: str = "mod") -> Layer:
    return Layer(name, root, "mod", "ok")


def _fs(root: Path, *relpaths: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    for i, rel in enumerate(relpaths):
        fs.add_file(root / rel, size=i + 1, mtime_ns=i + 10)
    return fs


def _populated(layer: Layer, fs: InMemoryFileSystem) -> LayerIndex:
    base = build_layer_index(layer, fs)
    entry = Entry("Ship", RefKind.ENTITY, layer.path / "GameInfo" / "Ship.entity", layer.name)
    return replace(base, names={RefKind.ENTITY: {"ship": entry}}, manifests={"entity": ["Ship"]})


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "layer"
    path.mkdir()
    return path


def test_default_cache_dir_is_under_platform_cache() -> None:
    assert default_cache_dir().name == "layers"


def test_serialization_round_trip(root: Path) -> None:
    layer = _layer(root)
    index = _populated(layer, _fs(root, "GameInfo/Ship.entity", "entity.manifest"))
    data = json.loads(json.dumps(serialize_index(index, VERSION)))
    assert deserialize_index(data, layer, VERSION, index.signature) == index


def test_serialized_paths_are_portable(root: Path) -> None:
    layer = _layer(root)
    index = _populated(layer, _fs(root, "GameInfo/Ship.entity"))
    text = json.dumps(serialize_index(index, VERSION))
    assert "GameInfo/Ship.entity" in text
    assert str(root / "GameInfo") not in text.replace(str(root.resolve()), "")


def test_disk_round_trip_across_instances(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "GameInfo/Ship.entity")
    index = _populated(layer, fs)
    cache_dir = tmp_path / "cache"
    LayerCache(cache_dir).put(index, VERSION)
    reloaded = LayerCache(cache_dir).get(layer, VERSION, index.signature)
    assert reloaded == index


def test_get_or_build_reuses_cached_names(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "GameInfo/Ship.entity")
    index = _populated(layer, fs)
    cache = LayerCache(tmp_path / "cache")
    cache.put(index, VERSION)
    assert cache.get_or_build(layer, VERSION, fs) == index
    assert LayerCache(tmp_path / "cache").get_or_build(layer, VERSION, fs) == index


def test_corrupt_file_is_discarded(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    cache = LayerCache(tmp_path / "cache")
    cache.put(build_layer_index(layer, fs), VERSION)
    file = cache.file_for(layer, VERSION)
    assert file is not None
    file.write_text("{not json", encoding="utf-8")
    fresh = LayerCache(tmp_path / "cache")
    index = fresh.get_or_build(layer, VERSION, fs)
    assert index.files
    assert json.loads(file.read_text(encoding="utf-8"))["signature"] == index.signature


def test_wrong_shape_file_is_discarded(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    signature = build_layer_index(layer, fs).signature
    cache = LayerCache(tmp_path / "cache")
    file = cache.file_for(layer, VERSION)
    assert file is not None
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps({"schema": SCHEMA_VERSION, "signature": signature}))
    assert cache.get(layer, VERSION, signature) is None
    assert not file.exists()


def test_stale_signature_is_discarded(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    cache = LayerCache(tmp_path / "cache")
    cache.put(_populated(layer, fs), VERSION)
    fs.add_file(root / "b.manifest", size=99, mtime_ns=5)
    index = LayerCache(tmp_path / "cache").get_or_build(layer, VERSION, fs)
    assert "b.manifest" in index.files
    assert not index.names


def test_stale_signature_drops_memory_entry(root: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    cache = LayerCache(use_disk=False)
    cache.put(_populated(layer, fs), VERSION)
    assert cache.get(layer, VERSION, "sha256:other") is None
    assert cache.get(layer, VERSION, build_layer_index(layer, fs).signature) is None


def test_schema_mismatch_is_discarded(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    index = build_layer_index(layer, fs)
    cache = LayerCache(tmp_path / "cache")
    cache.put(index, VERSION)
    file = cache.file_for(layer, VERSION)
    assert file is not None
    data = json.loads(file.read_text(encoding="utf-8"))
    data["schema"] = SCHEMA_VERSION + 1
    file.write_text(json.dumps(data), encoding="utf-8")
    assert LayerCache(tmp_path / "cache").get(layer, VERSION, index.signature) is None
    assert not file.exists()


def test_game_version_is_part_of_the_key(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    index = build_layer_index(layer, _fs(root, "a.manifest"))
    cache = LayerCache(tmp_path / "cache")
    cache.put(index, VERSION)
    assert cache.get(layer, GameVersion.VANILLA, index.signature) is None


def test_write_failure_is_ignored(root: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a directory")
    layer = _layer(root)
    fs = _fs(root, "a.manifest")
    cache = LayerCache(blocker / "cache")
    index = cache.get_or_build(layer, VERSION, fs)
    assert index.files
    assert cache.get(layer, VERSION, index.signature) == index


def test_replace_failure_is_ignored(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(layercache.os, "replace", fail)
    cache = LayerCache(tmp_path / "cache")
    index = cache.get_or_build(_layer(root), VERSION, _fs(root, "a.manifest"))
    assert index.files
    assert not list((tmp_path / "cache").glob("*"))


def test_non_serializable_manifests_skip_disk_only(root: Path, tmp_path: Path) -> None:
    layer = _layer(root)
    index = replace(build_layer_index(layer, _fs(root, "a.manifest")), manifests={"m": object()})
    cache = LayerCache(tmp_path / "cache")
    cache.put(index, VERSION)
    assert cache.get(layer, VERSION, index.signature) == index
    assert LayerCache(tmp_path / "cache").get(layer, VERSION, index.signature) is None


def test_memory_reused_across_projects(root: Path) -> None:
    fs = _fs(root, "GameInfo/Ship.entity")
    cache = LayerCache(use_disk=False)
    first = _populated(_layer(root, "shared"), fs)
    cache.put(first, VERSION)
    other = Layer("@alias", root, "mod", "ok")
    reused = cache.get_or_build(other, VERSION, fs)
    assert reused.layer == other
    assert reused.names[RefKind.ENTITY]["ship"].layer_name == "@alias"
    assert reused.files == first.files
    assert reused.signature == first.signature


def test_memory_only_cache_writes_nothing(root: Path, tmp_path: Path) -> None:
    cache = LayerCache(tmp_path / "unused", use_disk=False)
    cache.get_or_build(_layer(root), VERSION, _fs(root, "a.manifest"))
    assert cache.cache_dir is None
    assert not (tmp_path / "unused").exists()
