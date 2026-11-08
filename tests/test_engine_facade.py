"""Integration tests of the Engine facade over synthetic trees under ``tmp_path``."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine import facade as facade_module
from soase_validator.engine.chain import Layer
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.model import Diagnostic, Position, Severity
from soase_validator.engine.refindex import FileSystem, LayerIndex
from soase_validator.engine.registry import Registry, load_registry_from_texts
from soase_validator.engine.versions import GameVersion

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'
ENTITY_STUB = 'TXT2\nSinsArchiveVersion 194\nentityType "Stub"\n'
ENTITY_ENUMS = {"enums": [{"name": "entityType", "values": ["Stub"]}]}


def _registry() -> Registry:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [
                {"node": "field", "name": "b", "validation": "Brush"},
                {"node": "field", "name": "e", "validation": "Entity"},
            ],
        },
        {"name": "Stub", "children": []},
    ]
    return load_registry_from_texts(
        {
            "s.json": json.dumps({"structures": structures}),
            "enums.json": json.dumps(ENTITY_ENUMS),
        }
    )


class _RecordingCache(LayerCache):
    """Layer cache that records the Game Version of every index request."""

    def __init__(self) -> None:
        super().__init__(use_disk=False)
        self.versions: list[GameVersion] = []

    def get_or_build(
        self,
        layer: Layer,
        version: GameVersion,
        fs: FileSystem | None = None,
        language: str = "en",
    ) -> LayerIndex:
        self.versions.append(version)
        return super().get_or_build(layer, version, fs, language)


def _engine(tmp_path: Path, cache: LayerCache | None = None) -> Engine:
    return Engine(
        user_config_path=tmp_path / "no-user-file.json",
        env={},
        layer_cache=LayerCache(use_disk=False) if cache is None else cache,
        registry=_registry(),
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _config(root: Path, **settings: object) -> Path:
    return _write(root, "soase.json", json.dumps(settings))


def _codes(found: list[Diagnostic]) -> list[str]:
    return [d.code for d in found]


def _foo(brush: str) -> str:
    return f'TXT\nb "{brush}"\n'


@pytest.fixture
def tree(tmp_path: Path) -> Callable[[], tuple[Path, Path]]:
    """Build a parent mod that defines ``ParentBrush`` and a project above it."""

    def _build() -> tuple[Path, Path]:
        parent = tmp_path / "parent"
        project = tmp_path / "project"
        _write(parent, "Window/p.brushes", BRUSHES.format(name="ParentBrush"))
        _config(project, layers=["../parent"])
        return parent, project

    return _build


def test_unresolved_reference_is_reported_and_parent_reference_resolves(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    _, project = tree()
    engine = _engine(tmp_path)
    good = _write(project, "good.foo", _foo("parentbrush"))
    bad = _write(project, "bad.foo", _foo("Gone"))

    assert engine.validate_file(good) == []
    found = engine.validate_file(bad)

    assert _codes(found) == [dg.R010]
    assert "Gone" in found[0].message and "Brush" in found[0].message


def test_unsaved_text_is_validated_instead_of_the_file(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    _, project = tree()
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", _foo("ParentBrush"))

    assert engine.validate_file(file, _foo("Gone")) != []
    assert engine.validate_file(file) == []


def test_file_outside_the_mod_roots_gets_one_warning(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    tree()
    engine = _engine(tmp_path)
    outside = _write(tmp_path / "elsewhere", "a.foo", _foo("Gone"))

    found = engine.validate_file(outside)

    assert _codes(found) == [dg.C050]
    assert found[0].severity is Severity.WARNING
    assert found[0].file == outside
    assert found[0].range.start == Position(0, 0)
    assert str(outside) in found[0].message
    assert "manifest" in found[0].message and "modRoots" in found[0].message


def test_disabled_codes_hide_the_outside_warning(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    outside = _write(folder, "a.foo", _foo("Gone"))
    _config(folder, disabledCodes=[dg.C050], modRoots=["other"])
    engine = _engine(tmp_path)

    assert engine.validate_file(outside) == []


def test_directory_without_any_mod_root_file_gets_one_warning(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    _write(folder, "a.foo", _foo("Gone"))
    _write(folder, "sub/b.foo", _foo("Gone"))
    _write(folder, "notes.txt", "x")
    engine = _engine(tmp_path)

    results = engine.validate_directory(folder)

    assert list(results) == [folder]
    assert _codes(results[folder]) == [dg.C050]
    assert str(folder) in results[folder][0].message


def test_directory_with_only_unsupported_files_or_none_gives_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    unsupported = tmp_path / "unsupported"
    _write(unsupported, "notes.txt", "x")
    engine = _engine(tmp_path)

    assert engine.validate_directory(empty) == {}
    assert engine.validate_directory(unsupported) == {}


def test_directory_inside_a_mod_root_without_supported_files_gives_nothing(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _config(project)
    _write(project, "notes.txt", "x")
    engine = _engine(tmp_path)

    assert engine.validate_directory(project) == {}


def test_directory_mixing_inside_and_outside_files_skips_outside_silently(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    inside = _write(repo, "mod/a.foo", _foo("Gone"))
    _config(repo / "mod")
    outside = _write(repo, "loose/b.foo", _foo("Gone"))
    engine = _engine(tmp_path)

    results = engine.validate_directory(repo)

    assert set(results) == {inside}
    assert outside not in results
    assert dg.C050 not in _codes([d for found in results.values() for d in found])


def test_directory_warning_is_hidden_by_disabled_codes(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    _write(folder, "a.foo", _foo("Gone"))
    engine = _engine(tmp_path)
    engine.set_editor_settings({"disabledCodes": [dg.C050]})

    assert engine.validate_directory(folder) == {folder: []}


def test_parent_layer_files_are_not_validated(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    engine = _engine(tmp_path)
    file = _write(parent, "Window/read-only.foo", _foo("Gone"))
    settings = engine.resolve_settings(project)

    assert _codes(engine.validate_file(file, None, settings)) == [dg.C050]


def test_disabled_codes_are_removed_in_one_place(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _config(project, disabledCodes=["soase-r010"])
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", _foo("Gone"))
    unhidden = _write(project, "b.foo", 'b "Gone"\n')

    assert engine.validate_file(file) == []
    assert _codes(engine.validate_file(unhidden)) == [dg.P001]


def test_incomplete_chain_reports_layer_problem_and_limited_notice(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _config(project, layers=["../missing"])
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", _foo("Gone"))

    found = engine.validate_file(file)

    assert _codes(found) == [dg.C020, dg.C030]


def test_internal_error_returns_partial_diagnostics_and_logs_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "project"
    _config(project)
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", 'b "Gone"\n')

    def explode(*_args: object, **_kwargs: object) -> list[Diagnostic]:
        raise RuntimeError("boom")

    monkeypatch.setattr(facade_module, "validate", explode)
    with caplog.at_level(logging.ERROR):
        found = engine.validate_file(file)

    assert _codes(found) == [dg.P001, dg.X001]
    assert "boom" not in found[-1].message
    assert any(r.exc_info for r in caplog.records)
    assert capsys.readouterr().out == ""


def test_internal_error_in_directory_validation_is_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _config(project)
    _write(project, "a.foo", _foo("x"))
    engine = _engine(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_walk_into", explode)
    results = engine.validate_directory(project)

    assert [_codes(v) for v in results.values()] == [[dg.X001]]


def test_validate_directory_covers_supported_files_and_skips_hidden_directories(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    _, project = tree()
    engine = _engine(tmp_path)
    good = _write(project, "sub/good.foo", _foo("ParentBrush"))
    bad = _write(project, "bad.foo", _foo("Gone"))
    _write(project, "notes.txt", "not a mod file")
    _write(project, ".git/hidden.foo", _foo("Gone"))

    results = engine.validate_directory(project)

    assert set(results) == {good, bad}
    assert results[good] == []
    assert _codes(results[bad]) == [dg.R010]


def test_per_folder_soase_json_gives_each_overlay_its_own_chain(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(tmp_path / "parent-a", "Window/x.brushes", BRUSHES.format(name="OnlyInA"))
    _write(tmp_path / "parent-b", "Window/y.brushes", BRUSHES.format(name="OnlyInB"))
    _config(repo / "a", layers=["../../parent-a"])
    _config(repo / "b", layers=["../../parent-b"])
    in_a = _write(repo, "a/one.foo", _foo("OnlyInA"))
    in_b = _write(repo, "b/one.foo", _foo("OnlyInA"))
    engine = _engine(tmp_path)

    results = engine.validate_directory(repo)

    assert results[in_a] == []
    assert _codes(results[in_b]) == [dg.R010]


def test_nearest_soase_json_overrides_the_one_above_for_its_own_settings(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _config(repo, disabledCodes=["SOASE-R010"], modRoots=["."])
    _config(repo / "inner", modRoots=["."])
    outer = _write(repo, "outer.foo", _foo("Gone"))
    inner = _write(repo, "inner/inner.foo", _foo("Gone"))
    engine = _engine(tmp_path)

    results = engine.validate_directory(repo)

    assert results[outer] == []
    assert _codes(results[inner]) == []
    assert engine.resolve_settings(inner).disabled_codes == frozenset({"SOASE-R010"})


def test_on_file_saved_finds_dependents_when_a_referenced_name_appears_and_disappears(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    engine = _engine(tmp_path)
    dependent = _write(project, "dep.foo", _foo("NewBrush"))
    unrelated = _write(project, "other.foo", _foo("ParentBrush"))
    assert _codes(engine.validate_file(dependent)) == [dg.R010]
    assert engine.validate_file(unrelated) == []

    added = _write(parent, "Window/new.brushes", BRUSHES.format(name="NewBrush"))
    assert engine.on_file_saved(added) == {dependent}
    assert engine.validate_file(dependent) == []

    added.unlink()
    assert engine.on_file_saved(added) == {dependent}
    assert _codes(engine.validate_file(dependent)) == [dg.R010]


def test_on_file_saved_ignores_changes_below_an_overriding_layer(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    _write(project, "Window/mine.brushes", BRUSHES.format(name="Shared"))
    engine = _engine(tmp_path)
    dependent = _write(project, "dep.foo", _foo("Shared"))
    assert engine.validate_file(dependent) == []

    changed = _write(parent, "Window/shared.brushes", BRUSHES.format(name="Shared"))

    assert engine.on_file_saved(changed) == set()


def test_on_file_saved_for_an_unknown_path_changes_nothing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    assert engine.on_file_saved(tmp_path / "nothing.foo") == set()


def test_on_layer_files_changed_rescans_the_layer(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    engine = _engine(tmp_path)
    dependent = _write(project, "dep.foo", _foo("Later"))
    assert _codes(engine.validate_file(dependent)) == [dg.R010]

    _write(parent, "Window/later.brushes", BRUSHES.format(name="Later"))
    layer = engine._states[next(iter(engine._states))].chain.layers[0]
    assert engine.on_layer_files_changed(layer) == {dependent}
    assert engine.validate_file(dependent) == []


def test_changing_the_game_version_rebuilds_the_indexes(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    _, project = tree()
    cache = _RecordingCache()
    engine = _engine(tmp_path, cache)
    file = _write(project, "a.foo", _foo("ParentBrush"))
    engine.validate_file(file)
    first = set(cache.versions)

    _config(project, layers=["../parent"], gameVersion=GameVersion.REBELLION_194.value)
    assert engine.validate_file(file) == []

    assert first == {GameVersion.REBELLION_198}
    assert GameVersion.REBELLION_194 in cache.versions


def test_overlay_project_needs_no_manifests_and_reports_overrides_when_enabled(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    overlay = tmp_path / "overlay"
    _write(parent, "GameInfo/a.entity", ENTITY_STUB)
    _write(parent, "GameInfo/entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(parent, "Window/shared.brushes", BRUSHES.format(name="Shared"))
    shared = _write(overlay, "Window/shared.brushes", BRUSHES.format(name="Shared"))
    _write(overlay, "Window/own.brushes", BRUSHES.format(name="Own"))
    _config(overlay, layers=["../parent"])
    engine = _engine(tmp_path)

    assert engine.manifest_check(overlay) == []
    assert engine.validate_file(shared) == []

    _config(overlay, layers=["../parent"], reportOverrides=True)
    engine.reload_configuration()
    found = engine.validate_file(shared)

    assert _codes(found) == [dg.C040]
    assert found[0].severity is Severity.INFO
    assert "Layer parent" in found[0].message
    assert engine.validate_file(overlay / "Window/own.brushes") == []


def test_manifest_check_plan_and_apply_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _config(project)
    manifest = _write(project, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(project, "GameInfo/a.entity", ENTITY_STUB)
    unlisted = _write(project, "GameInfo/b.entity", ENTITY_STUB)
    engine = _engine(tmp_path)

    checked = engine.manifest_check(project)
    assert _codes(checked) == [dg.M010]
    assert [d.code for d in engine.validate_file(unlisted)] == [dg.M010]

    plan = engine.manifest_plan(project)
    assert [edit.added for edit in plan.edits] == [("b.entity",)]
    records = engine.manifest_apply(plan)

    assert [r.manifest_path for r in records] == [manifest]
    assert records[0].backup_path.is_file()
    assert engine.manifest_check(project) == []
    assert engine.validate_file(unlisted) == []


def test_manifest_add_edit_lists_only_the_requested_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _config(project)
    manifest = _write(project, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(project, "GameInfo/a.entity", ENTITY_STUB)
    first = _write(project, "GameInfo/b.entity", ENTITY_STUB)
    _write(project, "GameInfo/c.entity", ENTITY_STUB)
    engine = _engine(tmp_path)

    edit = engine.manifest_add_edit(first)

    assert edit is not None
    assert edit.manifest_path == manifest
    assert edit.added == ("b.entity",)
    assert edit.new_text == (
        'TXT\nentityNameCount 2\nentityName "a.entity"\nentityName "b.entity"\n'
    )
    assert manifest.read_text(encoding="utf-8") == edit.original_text


def test_manifest_add_edit_is_none_for_a_listed_file_and_a_lower_layer_manifest(
    tmp_path: Path,
) -> None:
    listed_project = tmp_path / "listed"
    _config(listed_project)
    _write(listed_project, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    listed = _write(listed_project, "GameInfo/a.entity", ENTITY_STUB)
    parent = tmp_path / "parent"
    _write(parent, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(parent, "GameInfo/a.entity", ENTITY_STUB)
    overlay = tmp_path / "overlay"
    _config(overlay, layers=["../parent"])
    added = _write(overlay, "GameInfo/b.entity", ENTITY_STUB)
    engine = _engine(tmp_path)

    assert engine.manifest_add_edit(listed) is None
    assert [d.code for d in engine.validate_file(added)] == [dg.M010]
    assert engine.manifest_add_edit(added) is None


def test_editor_settings_reach_every_call_below_the_environment_and_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _config(project)
    unlisted = _write(project, "GameInfo/b.entity", ENTITY_STUB)
    _write(project, "entity.manifest", "TXT\nentityNameCount 0\n")
    engine = _engine(tmp_path)
    assert [d.code for d in engine.validate_file(unlisted)] == [dg.M010]

    engine.set_editor_settings({"disabledCodes": [dg.M010]})
    assert engine.validate_file(unlisted) == []
    assert engine.resolve_settings(unlisted).disabled_codes == {dg.M010}

    engine.set_editor_settings(None)
    assert [d.code for d in engine.validate_file(unlisted)] == [dg.M010]


def test_chain_layers_lists_the_project_chain(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    layers = _engine(tmp_path).chain_layers(project / "Window")

    assert [layer.path for layer in layers][-1] == project
    assert parent in [layer.path for layer in layers]


def test_validate_directory_includes_manifest_findings_for_unsupported_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _config(project)
    manifest = _write(project, "entity.manifest", 'TXT\nentityNameCount 5\nentityName "a.entity"\n')
    unlisted = _write(project, "GameInfo/b.entity", ENTITY_STUB)
    _write(project, "GameInfo/a.entity", ENTITY_STUB)
    engine = _engine(tmp_path)

    results = engine.validate_directory(project)

    assert _codes(results[unlisted]) == [dg.M010]
    assert _codes(results[manifest]) == [dg.M030]


def test_entity_references_are_limited_to_files_the_governing_manifest_lists(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _config(project)
    _write(project, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "Listed.entity"\n')
    _write(project, "GameInfo/Listed.entity", ENTITY_STUB)
    _write(project, "GameInfo/Unlisted.entity", ENTITY_STUB)
    engine = _engine(tmp_path)
    listed = _write(project, "a.foo", 'TXT\ne "listed"\n')
    unlisted = _write(project, "b.foo", 'TXT\ne "Unlisted"\n')

    assert engine.validate_file(listed) == []
    assert _codes(engine.validate_file(unlisted)) == [dg.R010]


def test_changing_a_manifest_invalidates_every_validated_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _config(project)
    manifest = _write(project, "entity.manifest", "TXT\nentityNameCount 0\n")
    _write(project, "GameInfo/Late.entity", ENTITY_STUB)
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", 'TXT\ne "Late"\n')
    assert _codes(engine.validate_file(file)) == [dg.R010]

    manifest.write_text('TXT\nentityNameCount 1\nentityName "Late.entity"\n', encoding="utf-8")

    assert engine.on_file_saved(manifest) == {file}
    assert engine.validate_file(file) == []


def test_assistance_methods_use_the_projects_chain(
    tmp_path: Path, tree: Callable[[], tuple[Path, Path]]
) -> None:
    parent, project = tree()
    engine = _engine(tmp_path)
    file = _write(project, "a.foo", "")
    text = 'TXT\nb "Par"\n'

    items = engine.complete(file, text, Position(1, 6))
    definition = engine.definition(file, 'TXT\nb "ParentBrush"\n', Position(1, 5))

    assert [(i.label, i.detail) for i in items] == [("ParentBrush", parent.name)]
    assert definition is not None and definition.file == parent / "Window" / "p.brushes"
    assert engine.hover(file, 'TXT\nb "ParentBrush"\n', Position(1, 0)) is not None
    assert engine.hover(file, "TXT\nunknown 1\n", Position(1, 0)) is None


def test_field_help_and_entity_types_use_the_bundled_definitions() -> None:
    engine = Engine(env={}, layer_cache=LayerCache(use_disk=False))

    assert "Frigate" in engine.entity_types(GameVersion.REBELLION_198)
    assert engine.field_help("Galaxy", "no-such-field", GameVersion.REBELLION_198) is None
    assert isinstance(engine.load_warnings(), tuple)


def test_effective_config_reports_the_project_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config_file = _config(project, reportOverrides=True)
    engine = _engine(tmp_path)

    report = engine.effective_config(project / "x.foo")

    assert report.settings.report_overrides is True
    assert report.project_files == (config_file,)
