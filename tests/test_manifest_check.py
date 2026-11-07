"""Unit tests for governing-manifest selection and ``manifest_check``."""

from __future__ import annotations

from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.chain import Layer
from soase_validator.engine.config import ManifestPrefs
from soase_validator.engine.manifests import (
    governing_manifest,
    manifest_check,
    rule_for,
)
from soase_validator.engine.model import Severity
from soase_validator.engine.refindex import LayerIndex, build_layer_index


def _write(root: Path, relpath: str, text: str = "TXT\n") -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(count_key: str, name_key: str, names: list[str], count: int | None = None) -> str:
    total = len(names) if count is None else count
    lines = ["TXT", f"{count_key} {total}", *(f'{name_key} "{n}"' for n in names)]
    return "\n".join(lines) + "\n"


def _entities(names: list[str], count: int | None = None) -> str:
    return _manifest("entityNameCount", "entityName", names, count)


def _index(root: Path, kind: str = "project", name: str | None = None) -> LayerIndex:
    layer = Layer(name or root.name, root, kind, "ok")  # type: ignore[arg-type]
    return build_layer_index(layer)


def _codes(found) -> list[str]:
    return [d.code for d in found]


def test_unlisted_project_entity_reports_m010_naming_file_manifest_and_layer(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["a.entity"]))
    _write(root, "GameInfo/a.entity")
    _write(root, "GameInfo/B.entity")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M010]
    diag = found[0]
    assert diag.severity is Severity.ERROR
    assert diag.file == root / "GameInfo" / "B.entity"
    assert "B.entity" in diag.message and "entity.manifest" in diag.message
    assert "Layer mod" in diag.message
    assert "will not load" in diag.message and "fail to start" in diag.message
    assert "Add the entry" not in diag.message


def test_listing_is_case_insensitive(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["SHIP.ENTITY"]))
    _write(root, "GameInfo/ship.entity")

    assert manifest_check([_index(root)]) == []


def test_overlay_without_manifest_uses_lower_layer_manifest(tmp_path):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    _write(base, "entity.manifest", _entities(["reserved.entity"]))
    _write(base, "GameInfo/reserved.entity")
    _write(overlay, "GameInfo/reserved.entity")
    _write(overlay, "GameInfo/extra.entity")
    indexes = [_index(base, "mod"), _index(overlay)]

    rule = rule_for("entity.manifest")
    assert rule is not None
    governing = governing_manifest(indexes, rule)
    assert governing is not None and governing.index.layer.name == "base"

    found = manifest_check(indexes)
    assert _codes(found) == [dg.M010]
    assert found[0].file == overlay / "GameInfo" / "extra.entity"
    assert "Layer base" in found[0].message
    assert "Add the entry to base's manifest." in found[0].message


def test_highest_layer_manifest_governs(tmp_path):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    _write(base, "entity.manifest", _entities(["x.entity"]))
    _write(overlay, "entity.manifest", _entities([]))
    _write(overlay, "GameInfo/x.entity")
    indexes = [_index(base, "mod"), _index(overlay)]

    found = manifest_check(indexes)

    assert _codes(found) == [dg.M010]
    assert "Layer overlay" in found[0].message


def test_no_manifest_in_chain_reports_nothing(tmp_path):
    root = tmp_path / "mod"
    _write(root, "GameInfo/a.entity")

    assert manifest_check([_index(root)]) == []


def test_files_of_lower_layers_are_not_reported(tmp_path):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    _write(base, "entity.manifest", _entities([]))
    _write(base, "GameInfo/unlisted.entity")
    _write(overlay, "GameInfo/other.txt")

    assert manifest_check([_index(base, "mod"), _index(overlay)]) == []


def test_entity_outside_game_info_is_not_governed(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities([]))
    _write(root, "Other/a.entity")
    _write(root, "GameInfo/Nested/b.entity")

    assert manifest_check([_index(root)]) == []


def test_galaxy_manifest_names_carry_no_extension(tmp_path):
    root = tmp_path / "mod"
    _write(root, "galaxy.manifest", _manifest("fileCount", "fileName", ["Alpha"]))
    _write(root, "Galaxy/alpha.galaxy")
    _write(root, "Galaxy/beta.galaxy")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M010]
    assert found[0].file.name == "beta.galaxy"


def test_brush_files_are_governed_by_extension(tmp_path):
    root = tmp_path / "mod"
    _write(root, "brush.manifest", _manifest("brushFileCount", "brushFile", ["a.brushes"]))
    _write(root, "Window/a.brushes")
    _write(root, "Window/b.brushes")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M010]
    assert found[0].file.name == "b.brushes"


@pytest.mark.parametrize(
    ("manifest", "count_key", "name_key", "extension"),
    [
        ("brush.manifest", "brushFileCount", "brushFile", ".brushes"),
        ("playerPictures.manifest", "fileCount", "fileName", ".playerPictures"),
        ("playerThemes.manifest", "fileCount", "fileName", ".playerThemes"),
    ],
)
def test_window_manifests_govern_only_files_directly_in_window(
    tmp_path, manifest, count_key, name_key, extension
):
    root = tmp_path / "mod"
    _write(root, manifest, _manifest(count_key, name_key, []))
    _write(root, f"Window/a{extension}")
    _write(root, f"Other/b{extension}")
    _write(root, f"Window/Nested/c{extension}")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M010]
    assert found[0].file.name == f"a{extension}"


def test_skybox_manifest_governs_only_meshes_named_by_backdrop_data(tmp_path):
    root = tmp_path / "mod"
    _write(root, "skybox.manifest", _manifest("meshFileCount", "meshFileName", ["Sky1.MESH"]))
    _write(
        root,
        "GameInfo/sky.skyboxbackdropdata",
        'TXT\nnumProperties 2\nproperties\n\tmeshName "Sky1"\n\tmeshName "Sky2"\n',
    )
    _write(root, "Mesh/Sky1.MESH")
    _write(root, "Mesh/Sky2.MESH")
    _write(root, "Mesh/Rock.MESH")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M010]
    assert found[0].file.name == "Sky2.MESH"


def test_skybox_names_come_from_lower_layer_data(tmp_path):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    _write(base, "skybox.manifest", _manifest("meshFileCount", "meshFileName", []))
    _write(base, "GameInfo/sky.skyboxbackdropdata", 'TXT\nproperties\n\tmeshName "Sky1"\n')
    _write(overlay, "Mesh/sky1.mesh")

    found = manifest_check([_index(base, "mod"), _index(overlay)])

    assert _codes(found) == [dg.M010]


def test_base_game_unlisted_names_are_not_reported(tmp_path, monkeypatch):
    from soase_validator.engine import manifests

    rule = rule_for("entity.manifest")
    assert rule is not None
    patched = {
        "entity.manifest": type(rule)(
            **{
                **{f: getattr(rule, f) for f in rule.__slots__},
                "unlisted_by_base_game": ("Quiet.entity",),
            }
        )
    }
    monkeypatch.setattr(manifests, "load_manifest_rules", lambda: patched)
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities([]))
    _write(root, "GameInfo/quiet.entity")
    _write(root, "GameInfo/loud.entity")

    found = manifest_check([_index(root)])

    assert [d.file.name for d in found] == ["loud.entity"]


def test_exempt_unlisted_patterns_are_honoured(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities([]))
    _write(root, "GameInfo/Test_one.entity")
    _write(root, "GameInfo/real.entity")

    found = manifest_check([_index(root)], ManifestPrefs(exempt_unlisted=("test_*",)))

    assert [d.file.name for d in found] == ["real.entity"]


def test_listed_name_without_file_reports_m020_at_configured_severity(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["gone.entity", "here.entity"]))
    _write(root, "GameInfo/here.entity")

    default = manifest_check([_index(root)])
    strict = manifest_check([_index(root)], ManifestPrefs(unreferenced_severity=Severity.ERROR))

    assert _codes(default) == [dg.M020]
    assert default[0].severity is Severity.INFO
    assert default[0].file == root / "entity.manifest"
    assert default[0].range.start.line == 2
    assert strict[0].severity is Severity.ERROR


def test_m020_accepts_file_from_lower_layer_and_honours_exemptions(tmp_path):
    base = tmp_path / "base"
    mod = tmp_path / "mod"
    _write(base, "GameInfo/low.entity")
    _write(mod, "entity.manifest", _entities(["low.entity", "Reserved_x.entity", "gone.entity"]))

    found = manifest_check(
        [_index(base, "mod"), _index(mod)], ManifestPrefs(exempt_unreferenced=("reserved_*",))
    )

    assert [d.message.split()[0] for d in found] == ["gone.entity"]


def test_m020_for_extensionless_and_skybox_names(tmp_path):
    root = tmp_path / "mod"
    _write(root, "galaxy.manifest", _manifest("fileCount", "fileName", ["Alpha", "Missing"]))
    _write(root, "Galaxy/alpha.galaxy")
    _write(root, "skybox.manifest", _manifest("meshFileCount", "meshFileName", ["Sky1.MESH"]))
    _write(root, "Mesh/sky1.mesh")

    found = manifest_check([_index(root)])

    assert [d.message.split()[0] for d in found] == ["Missing"]


def test_count_mismatch_reports_m030_on_count_line(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["a.entity", "b.entity"], count=5))
    _write(root, "GameInfo/a.entity")
    _write(root, "GameInfo/b.entity")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M030]
    assert found[0].severity is Severity.ERROR
    assert found[0].range.start.line == 1


def test_duplicate_name_reports_m040_as_info(tmp_path):
    root = tmp_path / "mod"
    _write(root, "entity.manifest", _entities(["a.entity", "A.ENTITY"]))
    _write(root, "GameInfo/a.entity")

    found = manifest_check([_index(root)])

    assert _codes(found) == [dg.M040]
    assert found[0].severity is Severity.INFO
    assert found[0].range.start.line == 3
    assert "line 3" in found[0].message


def test_lower_layer_manifest_hygiene_is_not_reported(tmp_path):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    _write(base, "entity.manifest", _entities(["a.entity", "a.entity", "gone.entity"], count=9))
    _write(base, "GameInfo/a.entity")
    _write(overlay, "GameInfo/a.entity")

    assert manifest_check([_index(base, "mod"), _index(overlay)]) == []
