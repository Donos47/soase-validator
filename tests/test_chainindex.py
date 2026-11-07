"""Unit tests for name indexing, the merged Chain lookup and the C030 notice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.chain import Chain, Layer
from soase_validator.engine.chainindex import (
    ChainIndex,
    build_chain_index,
    limited_checks_notice,
)
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.model import Severity
from soase_validator.engine.nameindex import index_names
from soase_validator.engine.parser import parse
from soase_validator.engine.refindex import (
    Entry,
    InMemoryFileSystem,
    RefKind,
    build_layer_index,
)
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.engine.validator import (
    Found,
    NotFound,
    Unknown,
    ValidationContext,
    validate,
)
from soase_validator.engine.versions import GameVersion

VERSION = GameVersion.REBELLION_198
LOW = Path("/low")
HIGH = Path("/high")

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 2\nbrush\n\tname "{a}"\nbrush\n\tname "{b}"\n'
STR = 'TXT\nNumStrings 2\nStringInfo\n\tID "IDS_ONE"\n\tValue "One"\nStringInfo\n\tID "IDS_TWO"\n'
SOUND = 'TXT\nnumEffects 1\neffect\n\tname "{name}"\n\tfileName "x.ogg"\n'
MUSIC = 'TXT\nnumMusic 1\nmusic\n\tname "{name}"\n'
EXPLOSION = 'TXT\nexplosionEffectGroupCount 1\nexplosionEffectGroup\n\tgroupName "{name}"\n'
SCENARIO = (
    "TXT2\nSinsArchiveVersion 193\norbitBodyTypeCount 1\n"
    'starType\n\tdesignName "Star"\n\torbitBodyTypeCount 1\n\torbitBodyType "BlueStar"\n'
    'planetType\n\tdesignName "Desert"\n\torbitBodyTypeCount 0\n'
    'orbitBodyType\n\ttypeName "BlueStar"\n\tentityDefName "STAR_BLUE"\n'
    '\tdefaultTemplateName "Common"\n'
    'planetItemType\n\tdesignName "Mine"\n\tentityDefName "MINE"\n'
    'playerType\n\tdesignName "Loyalist"\n\tentityDefName "PLAYER_LOYALIST"\n'
    'planetItemsTemplate\n\ttemplateName "Common"\n\tsubTemplates 0\n\tgroups 0\n'
    'player\n\tdesignName "Player0"\n\tinGameName "One"\n'
)
GALAXY = (
    'TXT\nSinsArchiveVersion 193\nplayer\n\tdesignName "Local"\n'
    'template\n\ttemplateName "LocalTemplate"\n'
)


def _layer(path: Path, name: str, kind: str = "mod", status: str = "ok") -> Layer:
    return Layer(name, path, kind, status)  # type: ignore[arg-type]


def _add(fs: InMemoryFileSystem, root: Path, rel: str, text: str = "") -> None:
    fs.add_file(root / rel, size=len(text) + 1, mtime_ns=1, text=text)


def _index(fs: InMemoryFileSystem, layer: Layer):
    return index_names(build_layer_index(layer, fs), fs)


def _chain_index(
    fs: InMemoryFileSystem, *, complete: bool = True, governors: dict | None = None
) -> ChainIndex:
    low = _index(fs, _layer(LOW, "low", "game"))
    high = _index(fs, _layer(HIGH, "high", "project"))
    return ChainIndex((low, high), complete, governors or {})


def test_every_named_kind_is_read_from_its_defining_file() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Ship.entity")
    _add(fs, LOW, "Window/ui.brushes", BRUSHES.format(a="IconA", b="IconB"))
    _add(fs, LOW, "String/English.str", STR)
    _add(fs, LOW, "GameInfo/SoundEffects.sounddata", SOUND.format(name="BOOM"))
    _add(fs, LOW, "GameInfo/SoundMusic.sounddata", MUSIC.format(name="MUSIC_ONE"))
    _add(fs, LOW, "GameInfo/Explosions.explosiondata", EXPLOSION.format(name="CapitalShip0"))
    _add(fs, LOW, "GameInfo/GalaxyScenarioDef.galaxyScenarioDef", SCENARIO)
    names = _index(fs, _layer(LOW, "low")).names

    assert set(names[RefKind.ENTITY]) == {"ship"}
    assert set(names[RefKind.BRUSH]) == {"icona", "iconb"}
    assert set(names[RefKind.STRING_INFO]) == {"ids_one", "ids_two"}
    assert set(names[RefKind.SOUND]) == {"boom", "music_one"}
    assert set(names[RefKind.EXPLOSION]) == {"capitalship0"}
    assert set(names[RefKind.ORBIT_BODY_TYPE]) == {"bluestar"}
    assert set(names[RefKind.GALAXY_DESIGN]) == {"star", "desert", "mine", "loyalist", "player0"}
    assert set(names[RefKind.GALAXY_TEMPLATE]) == {"common"}
    assert names[RefKind.ENTITY]["ship"].name == "Ship"
    assert names[RefKind.ORBIT_BODY_TYPE]["bluestar"].layer_name == "low"


def test_files_outside_their_source_location_define_nothing() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Sub/Ship.entity")
    _add(fs, LOW, "Mesh/Ship.entity")
    _add(fs, LOW, "GameInfo/English.str", STR)
    _add(fs, LOW, "Window/Sound.sounddata", SOUND.format(name="BOOM"))
    _add(fs, LOW, "GameInfo/Unreadable.explosiondata")
    names = _index(fs, _layer(LOW, "low")).names

    assert RefKind.ENTITY not in names
    assert RefKind.STRING_INFO not in names
    assert RefKind.SOUND not in names
    assert RefKind.EXPLOSION not in names


def test_blocks_without_a_quoted_name_and_value_lines_define_nothing() -> None:
    fs = InMemoryFileSystem()
    scenario = SCENARIO + 'orbitBodyType\n\ttypeName 7\norbitBodyType "NotABlock"\n'
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", scenario)
    names = _index(fs, _layer(LOW, "low")).names

    assert set(names[RefKind.ORBIT_BODY_TYPE]) == {"bluestar"}


def test_highest_layer_wins_with_case_folding_and_reports_overridden_layer() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Window/ui.brushes", BRUSHES.format(a="Icon", b="Other"))
    _add(fs, HIGH, "Window/mod.brushes", BRUSHES.format(a="ICON", b="Extra"))
    index = _chain_index(fs)

    result = index.resolve("Brush", "icon")
    assert isinstance(result, Found)
    resolution = result.detail
    assert resolution.layer.name == "high"
    assert resolution.entry.name == "ICON"
    assert resolution.overrides is not None and resolution.overrides.name == "low"

    only_low = index.lookup("Brush", "OTHER")
    assert only_low is not None and only_low.layer.name == "low" and only_low.overrides is None


def test_name_missing_from_every_layer_is_not_found_on_a_complete_chain() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Window/ui.brushes", BRUSHES.format(a="Icon", b="Other"))

    assert isinstance(_chain_index(fs).resolve("Brush", "Missing"), NotFound)


def test_incomplete_chain_never_reports_not_found_but_still_finds() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Window/ui.brushes", BRUSHES.format(a="Icon", b="Other"))
    index = _chain_index(fs, complete=False)

    assert isinstance(index.resolve("Brush", "Missing"), Unknown)
    assert isinstance(index.resolve("Mesh", "Missing"), Unknown)
    assert isinstance(index.resolve("Brush", "icon"), Found)


def test_design_and_template_names_resolve_from_the_scenario_definition() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/GalaxyScenarioDef.galaxyScenarioDef", SCENARIO)
    index = _chain_index(fs)

    assert isinstance(index.resolve("GalaxyDesign", "desert"), Found)
    assert isinstance(index.resolve("GalaxyDesign", "PLAYER0"), Found)
    assert isinstance(index.resolve("GalaxyTemplate", "common"), Found)
    assert isinstance(index.resolve("GalaxyDesign", "Common"), NotFound)
    assert isinstance(index.resolve("GalaxyTemplate", "Desert"), NotFound)


def test_names_declared_by_a_galaxy_file_are_not_indexed() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Galaxy/Map.galaxy", GALAXY)
    index = _chain_index(fs)

    assert isinstance(index.resolve("GalaxyDesign", "Local"), NotFound)
    assert isinstance(index.resolve("GalaxyTemplate", "LocalTemplate"), NotFound)


def test_unknown_kinds_are_never_decided() -> None:
    index = _chain_index(InMemoryFileSystem())

    assert isinstance(index.resolve("NoSuchKind", "Anything"), Unknown)
    assert isinstance(index.resolve("MeshPoint", "Anything"), Unknown)


def test_file_references_resolve_through_the_same_lookup() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Mesh/Ship.MESH")
    _add(fs, HIGH, "Mesh/ship.mesh")
    _add(fs, LOW, "Textures/Flare.tga")
    index = _chain_index(fs)

    mesh = index.lookup("Mesh", "SHIP", ".entity")
    assert mesh is not None and mesh.layer.name == "high"
    assert mesh.overrides is not None and mesh.overrides.name == "low"
    assert isinstance(index.resolve("Texture", "flare"), Found)
    assert isinstance(index.resolve("Mesh", "Ship.mesh", ".entity"), NotFound)
    assert isinstance(index.resolve("Mesh", "Ship.mesh", ".particle"), Found)


def test_governor_limits_names_to_the_governing_manifest() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Listed.entity")
    _add(fs, LOW, "GameInfo/Unlisted.entity")

    def listed(entry: Entry) -> bool:
        return entry.name == "Listed"

    index = _chain_index(fs, governors={RefKind.ENTITY: listed})

    assert isinstance(index.resolve("Entity", "listed"), Found)
    assert isinstance(index.resolve("Entity", "Unlisted"), NotFound)


def test_chain_without_a_game_layer_resolves_against_usable_layers() -> None:
    fs = InMemoryFileSystem()
    _add(fs, HIGH, "GameInfo/Mine.entity")
    chain = Chain((_layer(HIGH, "high", "project"),), True)
    index = build_chain_index(chain, VERSION, LayerCache(use_disk=False), fs)

    assert isinstance(index.resolve("Entity", "mine"), Found)
    assert isinstance(index.resolve("Entity", "other"), NotFound)


def test_build_chain_index_skips_unavailable_layers_and_reuses_the_cache() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Ship.entity")
    layers = (
        _layer(Path("/gone"), "gone", "mod", "missing"),
        _layer(LOW, "low", "game"),
        _layer(HIGH, "high", "project"),
    )
    cache = LayerCache(use_disk=False)
    index = build_chain_index(Chain(layers, False), VERSION, cache, fs)

    assert [i.layer.name for i in index.indexes] == ["low", "high"]
    assert not index.complete
    again = build_chain_index(Chain(layers, False), VERSION, cache, fs)
    assert again.indexes[0] is index.indexes[0]


def test_limited_checks_notice_is_one_info_naming_the_missing_layers() -> None:
    layers = (
        _layer(Path("/base"), "base", "game", "unusable"),
        _layer(Path("/parent"), "@parent", "mod", "missing"),
        _layer(HIGH, "high", "project"),
    )
    notice = limited_checks_notice(Chain(layers, False), Path("a.entity"))

    assert len(notice) == 1
    only = notice[0]
    assert only.code == dg.C030 and only.severity is Severity.INFO
    assert "base is unusable" in only.message and "@parent is missing" in only.message
    assert "/base" in only.message.replace("\\", "/")
    assert "set-reference-root" in only.message


def test_limited_checks_notice_is_absent_when_complete_or_suppressed() -> None:
    project = _layer(HIGH, "high", "project")
    assert limited_checks_notice(Chain((project,), True), Path("a.entity")) == []
    missing = Chain((_layer(LOW, "low", "mod", "missing"), project), False)
    assert limited_checks_notice(missing, Path("a.entity"), suppressed=True) == []
    assert len(limited_checks_notice(missing, Path("a.entity"))) == 1


def _registry():
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [
                {"node": "field", "name": "b", "validation": "Brush"},
                {"node": "field", "name": "m", "validation": "Mesh"},
            ],
        }
    ]
    return load_registry_from_texts({"s.json": json.dumps({"structures": structures})})


def _validate(index: ChainIndex, body: str):
    path = Path("a.foo")
    ctx = ValidationContext(_registry(), VERSION, path, lookup=index)
    return validate(parse(f"TXT\n{body}", path), ctx)


def test_validator_reports_unresolved_reference_naming_type_and_value() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Window/ui.brushes", BRUSHES.format(a="Icon", b="Other"))
    index = _chain_index(fs)

    assert _validate(index, 'b "ICON"\n') == []
    diagnostics = _validate(index, 'b "Gone"\nm "Hull"\n')
    assert [d.code for d in diagnostics] == [dg.R010, dg.R010]
    assert "Brush" in diagnostics[0].message and "Gone" in diagnostics[0].message
    assert "Mesh" in diagnostics[1].message and "Hull" in diagnostics[1].message


def test_validator_reports_nothing_unresolved_on_an_incomplete_chain() -> None:
    index = _chain_index(InMemoryFileSystem(), complete=False)

    assert _validate(index, 'b "Gone"\nm "Hull"\n') == []


@pytest.mark.parametrize("kind", ["Brush", "Entity", "StringInfo", "Sound", "Explosion"])
def test_named_kinds_with_a_source_rule_are_decided_on_a_complete_chain(kind: str) -> None:
    assert isinstance(_chain_index(InMemoryFileSystem()).resolve(kind, "x"), NotFound)
