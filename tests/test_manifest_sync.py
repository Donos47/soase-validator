"""Unit tests for ``plan_sync``, ``plan_manifests`` and ``manifest_apply``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from soase_validator.engine import manifest_apply as apply_module
from soase_validator.engine.chain import Layer
from soase_validator.engine.manifest_apply import manifest_apply
from soase_validator.engine.manifests import (
    format_plan,
    parse_manifest,
    plan_manifests,
    plan_sync,
    rule_for,
)
from soase_validator.engine.refindex import LayerIndex, build_layer_index


def _rule(name: str):
    rule = rule_for(name)
    assert rule is not None
    return rule


def _write(root: Path, relpath: str, text: str = "TXT\n") -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _entities(names: list[str], eol: str = "\r\n", count: int | None = None) -> str:
    total = len(names) if count is None else count
    lines = ["TXT", f"entityNameCount {total}", *(f'entityName "{n}"' for n in names)]
    return eol.join(lines) + eol


def _index(root: Path, kind: str = "project") -> LayerIndex:
    return build_layer_index(Layer(root.name, root, kind, "ok"))  # type: ignore[arg-type]


def test_plan_sync_appends_names_and_rewrites_only_the_count_line() -> None:
    rule = _rule("entity.manifest")
    text = _entities(["b.entity", "a.entity"])

    result = plan_sync(text, rule, ["c.entity"])

    assert result == _entities(["b.entity", "a.entity", "c.entity"])


def test_plan_sync_keeps_lf_endings_header_and_missing_final_newline() -> None:
    rule = _rule("brush.manifest")
    text = 'TXT2\nbrushFileCount 1\nbrushFile "A.brushes"'

    result = plan_sync(text, rule, ["B.brushes", "C.brushes"])

    lines = ["TXT2", "brushFileCount 3", *(f'brushFile "{n}.brushes"' for n in "ABC")]
    assert result == "\n".join(lines)


def test_plan_sync_keeps_blank_lines_and_wrong_count_is_corrected() -> None:
    rule = _rule("entity.manifest")
    text = 'TXT\r\nentityNameCount 9\r\n\r\nentityName "a.entity"\r\n\r\n'

    result = plan_sync(text, rule, ["b.entity"])

    assert result == (
        'TXT\r\nentityNameCount 2\r\n\r\nentityName "a.entity"\r\nentityName "b.entity"\r\n\r\n'
    )


def test_plan_sync_skips_listed_names_ignoring_case_and_returns_input_unchanged() -> None:
    rule = _rule("entity.manifest")
    text = _entities(["A.entity"])

    assert plan_sync(text, rule, ["a.ENTITY"]) == text


def test_plan_sync_adds_missing_count_line_and_handles_empty_manifest() -> None:
    rule = _rule("galaxy.manifest")

    result = plan_sync("TXT\r\n", rule, ["Alpha"])

    assert result == 'TXT\r\nfileCount 1\r\nfileName "Alpha"\r\n'
    data = parse_manifest(result, rule)
    assert data.count == 1 and data.names == ("Alpha",)


def test_plan_sync_removes_every_matching_entry_only_when_asked() -> None:
    rule = _rule("entity.manifest")
    text = _entities(["a.entity", "gone.entity", "b.entity", "GONE.entity"])

    assert plan_sync(text, rule, []) == text
    assert plan_sync(text, rule, [], ["gone.entity"]) == _entities(["a.entity", "b.entity"])


def test_plan_manifests_covers_galaxy_names_without_extension(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    _write(root, "galaxy.manifest", 'TXT\nfileCount 1\nfileName "Alpha"\n')
    _write(root, "Galaxy/alpha.galaxy")
    _write(root, "Galaxy/Beta.galaxy")

    plan = plan_manifests([_index(root)])

    assert [edit.added for edit in plan.edits] == [("Beta",)]
    assert plan.edits[0].new_text == 'TXT\nfileCount 2\nfileName "Alpha"\nfileName "Beta"\n'
    assert plan.advisories == ()


def test_plan_manifests_skybox_adds_only_meshes_named_by_backdrop_data(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    _write(root, "skybox.manifest", 'TXT\nmeshFileCount 1\nmeshFileName "Sky1.MESH"\n')
    _write(
        root,
        "GameInfo/sky.skyboxbackdropdata",
        'TXT\nproperties\n\tmeshName "Sky1"\n\tmeshName "Sky2"\n',
    )
    _write(root, "Mesh/sky1.mesh")
    _write(root, "Mesh/Sky2.mesh")
    _write(root, "Mesh/Unrelated.mesh")

    plan = plan_manifests([_index(root)])

    assert [edit.added for edit in plan.edits] == [("Sky2.mesh",)]


def test_overlay_without_manifests_yields_an_empty_plan(tmp_path: Path) -> None:
    root = tmp_path / "overlay"
    _write(root, "GameInfo/extra.entity")

    plan = plan_manifests([_index(root)])

    assert plan.edits == () and plan.advisories == ()
    assert format_plan(plan) == ""


def test_lower_layer_manifest_yields_advisory_and_is_not_edited(tmp_path: Path) -> None:
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    manifest = _write(base, "entity.manifest", _entities(["reserved.entity"]))
    before = manifest.read_bytes()
    _write(overlay, "GameInfo/extra.entity")

    plan = plan_manifests([_index(base, "mod"), _index(overlay)])

    assert plan.edits == ()
    assert len(plan.advisories) == 1
    advisory = plan.advisories[0]
    assert (advisory.layer_name, advisory.names) == ("base", ("extra.entity",))
    assert advisory.manifest_path == manifest
    assert "extra.entity" in format_plan(plan)
    assert manifest_apply(plan) == []
    assert manifest.read_bytes() == before


def test_stale_entries_are_removed_only_with_remove_stale(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["a.entity", "ghost.entity"]))
    _write(root, "GameInfo/a.entity")

    assert plan_manifests([_index(root)]).edits == ()
    plan = plan_manifests([_index(root)], remove_stale=True)

    assert [edit.removed for edit in plan.edits] == [("ghost.entity",)]
    assert plan.edits[0].new_text == _entities(["a.entity"])


def test_format_plan_prints_unified_diff(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["a.entity"]))
    _write(root, "GameInfo/b.entity")

    text = format_plan(plan_manifests([_index(root)]))

    assert "--- entity.manifest (current)" in text
    assert '+entityName "b.entity"' in text
    assert "+entityNameCount 2" in text


def _planned_entity_edit(tmp_path: Path, text: str | None = None):
    root = tmp_path / "mod"
    manifest = _write(root, "entity.manifest", text or _entities(["a.entity"]))
    _write(root, "GameInfo/b.entity")
    return manifest, plan_manifests([_index(root)])


def test_apply_writes_backup_and_new_text_and_keeps_line_endings(tmp_path: Path) -> None:
    manifest, plan = _planned_entity_edit(tmp_path)
    original = manifest.read_bytes()

    records = manifest_apply(plan)

    assert [r.manifest_path for r in records] == [manifest]
    assert records[0].backup_path == manifest.with_name("entity.manifest.old")
    assert records[0].backup_path.read_bytes() == original
    assert manifest.read_bytes() == _entities(["a.entity", "b.entity"]).encode()


def test_apply_overwrites_existing_backup_with_current_manifest(tmp_path: Path) -> None:
    manifest, plan = _planned_entity_edit(tmp_path)
    original = manifest.read_bytes()
    backup = manifest.with_name("entity.manifest.old")
    backup.write_text("stale")

    records = manifest_apply(plan)

    assert records[0].backup_path == backup
    assert backup.read_bytes() == original
    assert not manifest.with_name("entity.manifest.old.1").exists()


def test_apply_preserves_bom(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    manifest = root / "entity.manifest"
    root.mkdir()
    manifest.write_bytes(b"\xef\xbb\xbf" + _entities(["a.entity"]).encode())
    _write(root, "GameInfo/b.entity")

    manifest_apply(plan_manifests([_index(root)]))

    assert manifest.read_bytes().startswith(b"\xef\xbb\xbf")


def test_failed_replace_leaves_original_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, plan = _planned_entity_edit(tmp_path)
    original = manifest.read_bytes()

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(apply_module.os, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        manifest_apply(plan)

    assert manifest.read_bytes() == original
    assert sorted(p.name for p in manifest.parent.iterdir() if p.is_file()) == [
        "entity.manifest",
        "entity.manifest.old",
    ]
    assert os.path.exists(manifest)


def test_apply_refuses_a_manifest_that_changed_since_planning(tmp_path: Path) -> None:
    manifest, plan = _planned_entity_edit(tmp_path)
    manifest.write_bytes(_entities(["a.entity", "x.entity"]).encode())

    with pytest.raises(ValueError, match="changed since"):
        manifest_apply(plan)

    assert not manifest.with_name("entity.manifest.old").exists()
