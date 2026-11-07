"""Unit tests for incremental name updates and dependency tracking."""

from __future__ import annotations

from pathlib import Path

from soase_validator.engine.chain import Layer
from soase_validator.engine.chainindex import ChainIndex
from soase_validator.engine.deptracker import (
    DependencyTracker,
    IndexDelta,
    RecordingLookup,
    ResolvedRef,
    diff_layer_index,
)
from soase_validator.engine.nameindex import index_names
from soase_validator.engine.refindex import (
    InMemoryFileSystem,
    LayerIndex,
    RefKind,
    build_layer_index,
    update_file,
)
from soase_validator.engine.validator import Found, NotFound, Unknown

LOW = Path("/low")
MID = Path("/mid")
HIGH = Path("/high")
LOW_LAYER = Layer("low", LOW, "game", "ok")
MID_LAYER = Layer("mid", MID, "mod", "ok")
HIGH_LAYER = Layer("high", HIGH, "project", "ok")
LAYERS = (LOW_LAYER, MID_LAYER, HIGH_LAYER)

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'
STR = 'TXT\nNumStrings 1\nStringInfo\n\tID "{name}"\n\tValue "x"\n'
SOUND = 'TXT\nnumEffects 1\neffect\n\tname "{name}"\n\tfileName "x.ogg"\n'
EXPLOSION = 'TXT\nexplosionEffectGroupCount 1\nexplosionEffectGroup\n\tgroupName "{name}"\n'
SCENARIO = (
    "TXT2\nSinsArchiveVersion 193\norbitBodyTypeCount 1\n"
    'orbitBodyType\n\ttypeName "{name}"\n\tentityDefName "E"\n'
)

DEFINING_FILES = {
    "GameInfo/a.entity": ("", RefKind.ENTITY, "a"),
    "Window/a.brushes": (BRUSHES, RefKind.BRUSH, "B1"),
    "String/a.str": (STR, RefKind.STRING_INFO, "IDS_1"),
    "GameInfo/a.sounddata": (SOUND, RefKind.SOUND, "S1"),
    "GameInfo/a.explosiondata": (EXPLOSION, RefKind.EXPLOSION, "X1"),
    "GameInfo/a.galaxyScenarioDef": (SCENARIO, RefKind.ORBIT_BODY_TYPE, "O1"),
}


def _put(fs: InMemoryFileSystem, root: Path, rel: str, text: str = "", mtime: int = 1) -> None:
    fs.add_file(root / rel, size=len(text) + 1, mtime_ns=mtime, text=text)


def _index(fs: InMemoryFileSystem, layer: Layer) -> LayerIndex:
    return index_names(build_layer_index(layer, fs), fs)


def _incremental(index: LayerIndex, fs: InMemoryFileSystem, root: Path, rel: str) -> LayerIndex:
    return update_file(index, root / rel, fs)


def test_update_file_adds_names_like_a_full_rebuild() -> None:
    for rel, (template, _kind, name) in DEFINING_FILES.items():
        fs = InMemoryFileSystem()
        _put(fs, LOW, "Mesh/keep.mesh")
        index = _index(fs, LOW_LAYER)
        _put(fs, LOW, rel, template.replace("{name}", name))
        assert _incremental(index, fs, LOW, rel) == _index(fs, LOW_LAYER), rel


def test_update_file_replaces_names_after_edit_and_drops_them_after_delete() -> None:
    for rel, (template, _kind, name) in DEFINING_FILES.items():
        fs = InMemoryFileSystem()
        _put(fs, LOW, rel, template.replace("{name}", name))
        index = _index(fs, LOW_LAYER)
        _put(fs, LOW, rel, template.replace("{name}", "Other"), mtime=2)
        index = _incremental(index, fs, LOW, rel)
        assert index == _index(fs, LOW_LAYER), rel
        fs.remove_file(LOW / rel)
        index = _incremental(index, fs, LOW, rel)
        assert index == _index(fs, LOW_LAYER), rel
        assert not index.names, rel


def test_update_file_falls_back_to_the_next_definer_of_a_shared_name() -> None:
    fs = InMemoryFileSystem()
    _put(fs, LOW, "Window/a.brushes", BRUSHES.replace("{name}", "Shared"))
    _put(fs, LOW, "Window/b.brushes", BRUSHES.replace("{name}", "shared"))
    index = _index(fs, LOW_LAYER)
    assert index.names[RefKind.BRUSH]["shared"].file == LOW / "Window/a.brushes"
    fs.remove_file(LOW / "Window/a.brushes")
    index = _incremental(index, fs, LOW, "Window/a.brushes")
    assert index == _index(fs, LOW_LAYER)
    assert index.names[RefKind.BRUSH]["shared"].file == LOW / "Window/b.brushes"
    _put(fs, LOW, "Window/a.brushes", BRUSHES.replace("{name}", "Shared"))
    assert _incremental(index, fs, LOW, "Window/a.brushes") == _index(fs, LOW_LAYER)


def test_update_file_for_a_non_defining_file_keeps_names() -> None:
    fs = InMemoryFileSystem()
    _put(fs, LOW, "GameInfo/a.entity")
    index = _index(fs, LOW_LAYER)
    _put(fs, LOW, "Mesh/m.mesh")
    updated = _incremental(index, fs, LOW, "Mesh/m.mesh")
    assert updated.names == index.names


def test_recording_lookup_records_every_outcome() -> None:
    fs = InMemoryFileSystem()
    _put(fs, LOW, "GameInfo/ship.entity")
    chain = ChainIndex((_index(fs, LOW_LAYER),), True)
    recorder = RecordingLookup(chain)
    assert isinstance(recorder.resolve("Entity", "SHIP"), Found)
    assert isinstance(recorder.resolve("Entity", "Gone"), NotFound)
    assert isinstance(recorder.resolve("Mesh", "M.mesh", ".particle"), NotFound)
    assert isinstance(recorder.resolve("Other", "x"), Unknown)
    assert recorder.references == {
        ResolvedRef(LOW_LAYER, RefKind.ENTITY, "ship"),
        ResolvedRef(None, RefKind.ENTITY, "gone"),
        ResolvedRef(None, RefKind.MESH, "m.mesh", ".particle"),
    }


def test_recording_lookup_records_unknown_results_of_an_incomplete_chain() -> None:
    chain = ChainIndex((), False)
    recorder = RecordingLookup(chain)
    assert isinstance(recorder.resolve("Brush", "B"), Unknown)
    assert recorder.references == {ResolvedRef(None, RefKind.BRUSH, "b")}


def test_diff_layer_index_reports_added_and_removed_names_and_files() -> None:
    fs = InMemoryFileSystem()
    _put(fs, LOW, "GameInfo/a.entity")
    old = _index(fs, LOW_LAYER)
    fs.remove_file(LOW / "GameInfo/a.entity")
    _put(fs, LOW, "GameInfo/b.entity")
    delta = diff_layer_index(old, _index(fs, LOW_LAYER))
    assert delta.names == {(RefKind.ENTITY, "a"), (RefKind.ENTITY, "b")}
    assert delta.files == {"gameinfo/a.entity", "gameinfo/b.entity"}
    assert diff_layer_index(old, old).empty
    assert diff_layer_index(None, old).names == {(RefKind.ENTITY, "a")}


def _tracker(*refs: tuple[str, ResolvedRef]) -> DependencyTracker:
    tracker = DependencyTracker()
    for name, ref in refs:
        tracker.record(Path(name), [ref])
    return tracker


def _names(layer: Layer, *pairs: tuple[RefKind, str]) -> IndexDelta:
    return IndexDelta(layer, frozenset(pairs))


def test_unresolved_reference_is_a_dependent_when_the_name_appears() -> None:
    tracker = _tracker(("a", ResolvedRef(None, RefKind.ENTITY, "ship")))
    for layer in LAYERS:
        found = tracker.dependents([_names(layer, (RefKind.ENTITY, "ship"))], LAYERS)
        assert found == {Path("a")}


def test_change_above_the_provider_is_a_dependent() -> None:
    tracker = _tracker(("a", ResolvedRef(MID_LAYER, RefKind.BRUSH, "b")))
    delta = _names(HIGH_LAYER, (RefKind.BRUSH, "b"))
    assert tracker.dependents([delta], LAYERS) == {Path("a")}


def test_change_in_the_provider_is_a_dependent() -> None:
    tracker = _tracker(("a", ResolvedRef(MID_LAYER, RefKind.BRUSH, "b")))
    delta = _names(MID_LAYER, (RefKind.BRUSH, "b"))
    assert tracker.dependents([delta], LAYERS) == {Path("a")}


def test_change_below_the_provider_is_overridden_and_not_a_dependent() -> None:
    tracker = _tracker(("a", ResolvedRef(MID_LAYER, RefKind.BRUSH, "b")))
    delta = _names(LOW_LAYER, (RefKind.BRUSH, "b"))
    assert tracker.dependents([delta], LAYERS) == frozenset()


def test_other_names_kinds_and_untracked_layers_are_ignored() -> None:
    tracker = _tracker(("a", ResolvedRef(None, RefKind.BRUSH, "b")))
    outside = Layer("x", Path("/x"), "mod", "ok")
    assert not tracker.dependents([_names(HIGH_LAYER, (RefKind.BRUSH, "c"))], LAYERS)
    assert not tracker.dependents([_names(HIGH_LAYER, (RefKind.ENTITY, "b"))], LAYERS)
    assert not tracker.dependents([_names(outside, (RefKind.BRUSH, "b"))], LAYERS)


def test_file_reference_matches_candidate_file_keys() -> None:
    tracker = _tracker(
        ("a", ResolvedRef(None, RefKind.TEXTURE, "icon.dds")),
        ("b", ResolvedRef(None, RefKind.MESH, "ship", ".entity")),
    )
    texture = IndexDelta(HIGH_LAYER, files=frozenset({"textures/icon.dds"}))
    mesh = IndexDelta(HIGH_LAYER, files=frozenset({"mesh/ship.mesh"}))
    assert tracker.dependents([texture], LAYERS) == {Path("a")}
    assert tracker.dependents([mesh], LAYERS) == {Path("b")}


def test_record_replaces_and_forget_removes() -> None:
    tracker = DependencyTracker()
    file = Path("a")
    tracker.record(file, [ResolvedRef(None, RefKind.BRUSH, "b")])
    tracker.record(file, [ResolvedRef(None, RefKind.BRUSH, "c")])
    assert not tracker.dependents([_names(HIGH_LAYER, (RefKind.BRUSH, "b"))], LAYERS)
    assert tracker.dependents([_names(HIGH_LAYER, (RefKind.BRUSH, "c"))], LAYERS) == {file}
    tracker.forget(file)
    assert tracker.tracked() == frozenset()


def test_end_to_end_save_in_a_lower_layer_revalidates_unresolved_dependent() -> None:
    fs = InMemoryFileSystem()
    _put(fs, LOW, "GameInfo/ship.entity")
    low = _index(fs, LOW_LAYER)
    high = _index(fs, HIGH_LAYER)
    recorder = RecordingLookup(ChainIndex((low, high), True))
    recorder.resolve("Entity", "Frigate")
    recorder.resolve("Entity", "Ship")
    tracker = DependencyTracker()
    tracker.record(HIGH / "GameInfo/user.entity", recorder.references)

    _put(fs, LOW, "GameInfo/frigate.entity")
    new_low = _incremental(low, fs, LOW, "GameInfo/frigate.entity")
    delta = diff_layer_index(low, new_low)
    assert tracker.dependents([delta], (LOW_LAYER, HIGH_LAYER)) == {HIGH / "GameInfo/user.entity"}
