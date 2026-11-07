"""Tests for localized name sources, built-in tokens and constants-defined designs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.chain import Chain, Layer
from soase_validator.engine.chainindex import (
    BuiltinResolution,
    ChainIndex,
    Resolution,
    build_chain_index,
)
from soase_validator.engine.deptracker import (
    IndexDelta,
    ResolvedRef,
    affected_files,
    diff_layer_index,
)
from soase_validator.engine.layercache import LayerCache, deserialize_index, serialize_index
from soase_validator.engine.nameindex import index_names, update_names
from soase_validator.engine.parser import parse
from soase_validator.engine.refindex import (
    InMemoryFileSystem,
    LayerIndex,
    RefKind,
    build_layer_index,
    find_file,
    update_file,
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

STR = 'TXT\nNumStrings 1\nStringInfo\n\tID "{id}"\n\tValue "text"\n'
CONSTANTS = (
    "TXT2\nSinsArchiveVersion 194\nGameplayConstants\n"
    "\tpingTime 10\n"
    "\tminorFactionsData\n"
    "\t\tminorFactionPlayerDefCount 2\n"
    '\t\tminorFactionPlayerDef\n\t\t\tname "DefaultTech"\n'
    '\t\tminorFactionPlayerDef\n\t\t\tname "TechMiners"\n'
    '\tminorFactionPlayerDef\n\t\t\tname "WrongLevel"\n'
)
GSD = (
    "TXT2\nSinsArchiveVersion 194\n"
    'player\n\tdesignName "Pirate"\n'
    'player\n\tdesignName "{militia}"\n'
)


def _layer(path: Path, name: str, kind: str = "mod") -> Layer:
    return Layer(name, path, kind, "ok")  # type: ignore[arg-type]


def _add(fs: InMemoryFileSystem, root: Path, rel: str, text: str = "") -> None:
    fs.add_file(root / rel, size=len(text) + 1, mtime_ns=1, text=text)


def _chain(
    fs: InMemoryFileSystem,
    language: str,
    roots: tuple[Path, ...] = (LOW,),
    *,
    complete: bool = True,
) -> ChainIndex:
    layers = tuple(_layer(root, root.name) for root in roots)
    return build_chain_index(
        Chain(layers, complete), VERSION, LayerCache(use_disk=False), fs, language=language
    )


def _provider(index: ChainIndex, kind: str, name: str) -> str | None:
    result = index.resolve(kind, name)
    if not isinstance(result, Found):
        return None
    assert isinstance(result.detail, Resolution)
    return result.detail.entry.file.relative_to(result.detail.layer.path).as_posix()


def test_string_names_come_from_the_configured_language() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/de/String/English.str", STR.format(id="IDS_DE"))
    _add(fs, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_EN"))

    german = _chain(fs, "de")

    assert _provider(german, "StringInfo", "ids_de") == "Localizations/de/String/English.str"
    assert _provider(german, "StringInfo", "IDS_EN") == "Localizations/en/String/English.str"
    english = _chain(fs, "en")
    assert isinstance(english.resolve("StringInfo", "IDS_DE"), NotFound)


def test_string_name_missing_from_the_configured_language_falls_back_to_en() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/fr/String/English.str", STR.format(id="IDS_FR"))
    _add(fs, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_ONLY_EN"))

    index = _chain(fs, "fr")

    assert isinstance(index.resolve("StringInfo", "IDS_ONLY_EN"), Found)
    assert isinstance(index.resolve("StringInfo", "IDS_FR"), Found)


def test_string_name_in_neither_the_configured_language_nor_en_is_unresolved() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/fr/String/English.str", STR.format(id="IDS_FR"))
    _add(fs, LOW, "Localizations/de/String/English.str", STR.format(id="IDS_DE"))
    _add(fs, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_EN"))

    index = _chain(fs, "fr")

    assert isinstance(index.resolve("StringInfo", "IDS_DE"), NotFound)
    assert isinstance(index.resolve("StringInfo", "IDS_MISSING"), NotFound)


def test_string_names_resolve_from_the_legacy_layout() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "String/English.str", STR.format(id="IDS_LEGACY"))

    assert isinstance(_chain(fs, "de").resolve("StringInfo", "ids_legacy"), Found)
    assert isinstance(_chain(fs, "en").resolve("StringInfo", "IDS_OTHER"), NotFound)


def test_within_a_layer_the_configured_language_beats_en_and_en_beats_legacy() -> None:
    fs = InMemoryFileSystem()
    for rel in (
        "String/English.str",
        "Localizations/en/String/English.str",
        "Localizations/de/String/English.str",
    ):
        _add(fs, LOW, rel, STR.format(id="IDS_SAME"))

    assert _provider(_chain(fs, "de"), "StringInfo", "IDS_SAME") == (
        "Localizations/de/String/English.str"
    )
    assert _provider(_chain(fs, "fr"), "StringInfo", "IDS_SAME") == (
        "Localizations/en/String/English.str"
    )
    legacy = InMemoryFileSystem()
    _add(legacy, LOW, "String/English.str", STR.format(id="IDS_SAME"))
    _add(legacy, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_SAME"))
    assert _provider(_chain(legacy, "de"), "StringInfo", "IDS_SAME") == (
        "Localizations/en/String/English.str"
    )


def test_mixed_layouts_across_layers_let_the_highest_layer_win() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_SAME"))
    _add(fs, LOW, "Localizations/en/String/Other.str", STR.format(id="IDS_LOW_ONLY"))
    _add(fs, HIGH, "String/English.str", STR.format(id="IDS_SAME"))

    index = _chain(fs, "en", (LOW, HIGH))

    result = index.resolve("StringInfo", "IDS_SAME")
    assert isinstance(result, Found) and isinstance(result.detail, Resolution)
    assert result.detail.layer.name == "high"
    assert result.detail.overrides is not None and result.detail.overrides.name == "low"
    assert isinstance(index.resolve("StringInfo", "IDS_LOW_ONLY"), Found)


def test_string_files_below_a_language_folder_subdirectory_define_nothing() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/en/String/Sub/English.str", STR.format(id="IDS_DEEP"))
    _add(fs, LOW, "Localizations/en/Font/English.str", STR.format(id="IDS_FONT"))

    index = _chain(fs, "en")

    assert isinstance(index.resolve("StringInfo", "IDS_DEEP"), NotFound)
    assert isinstance(index.resolve("StringInfo", "IDS_FONT"), NotFound)


def test_sound_files_follow_the_same_language_order() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/de/Sound/OnlyDe.ogg")
    _add(fs, LOW, "Localizations/en/Sound/OnlyEn.ogg")
    _add(fs, LOW, "Localizations/de/Sound/Both.ogg")
    _add(fs, LOW, "Localizations/en/Sound/Both.ogg")
    _add(fs, LOW, "Sound/Legacy.ogg")
    german = _chain(fs, "de")
    english = _chain(fs, "en")

    assert _provider(german, "SoundFile", "OnlyDe.ogg") == "Localizations/de/Sound/OnlyDe.ogg"
    assert _provider(german, "SoundFile", "onlyen") == "Localizations/en/Sound/OnlyEn.ogg"
    assert _provider(german, "SoundFile", "Both.ogg") == "Localizations/de/Sound/Both.ogg"
    assert _provider(english, "SoundFile", "Both.ogg") == "Localizations/en/Sound/Both.ogg"
    assert _provider(german, "SoundFile", "Legacy") == "Sound/Legacy.ogg"
    assert isinstance(english.resolve("SoundFile", "OnlyDe.ogg"), NotFound)
    assert isinstance(german.resolve("SoundFile", "Missing.ogg"), NotFound)


def test_sound_files_mix_layouts_across_layers() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/en/Sound/Shared.ogg")
    _add(fs, HIGH, "Sound/Shared.ogg")
    index = _chain(fs, "en", (LOW, HIGH))

    result = index.resolve("SoundFile", "Shared")

    assert isinstance(result, Found) and isinstance(result.detail, Resolution)
    assert result.detail.layer.name == "high" and result.detail.overrides is not None
    assert result.detail.overrides.name == "low"


def test_find_file_takes_the_language() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/it/Sound/Voice.ogg")
    index = build_layer_index(_layer(LOW, "low"), fs)

    assert find_file([index], "SoundFile", "Voice", language="it") == (
        LOW / "Localizations/it/Sound/Voice.ogg"
    )
    assert find_file([index], "SoundFile", "Voice", language="de") is None
    assert find_file([index], "SoundFile", "Voice") is None


def test_language_is_compared_casefolded() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/zh-CN/String/English.str", STR.format(id="IDS_ZH"))
    _add(fs, LOW, "Localizations/zh-CN/Sound/Voice.ogg")

    index = _chain(fs, "ZH-cn")

    assert isinstance(index.resolve("StringInfo", "IDS_ZH"), Found)
    assert isinstance(index.resolve("SoundFile", "Voice"), Found)


def test_cache_keeps_one_index_per_language(tmp_path: Path) -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/de/String/English.str", STR.format(id="IDS_DE"))
    layer = _layer(LOW, "low")
    cache = LayerCache(tmp_path / "cache")

    german = cache.get_or_build(layer, VERSION, fs, "de")
    english = cache.get_or_build(layer, VERSION, fs, "en")
    again = LayerCache(tmp_path / "cache").get_or_build(layer, VERSION, fs, "de")

    assert "ids_de" in german.names[RefKind.STRING_INFO]
    assert RefKind.STRING_INFO not in english.names
    assert again == german
    assert cache.file_for(layer, VERSION, "de") != cache.file_for(layer, VERSION, "en")
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


def test_stored_index_of_another_language_is_rejected() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/de/String/English.str", STR.format(id="IDS_DE"))
    layer = _layer(LOW, "low")
    index = index_names(build_layer_index(layer, fs), fs, "de")

    data = serialize_index(index, VERSION)

    assert deserialize_index(data, layer, VERSION, index.signature, "de") == index
    assert deserialize_index(data, layer, VERSION, index.signature, "en") is None


def test_incremental_update_equals_a_rebuild_for_localized_files() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "Localizations/en/String/English.str", STR.format(id="IDS_SAME"))
    layer = _layer(LOW, "low")
    index = index_names(build_layer_index(layer, fs), fs, "de")
    assert RefKind.STRING_INFO in index.names

    path = LOW / "Localizations/de/String/English.str"
    _add(fs, LOW, "Localizations/de/String/English.str", STR.format(id="IDS_SAME"))
    updated = update_file(index, path, fs)

    rebuilt = index_names(build_layer_index(layer, fs), fs, "de")
    assert updated.language == "de"
    assert updated.names == rebuilt.names
    assert updated.names[RefKind.STRING_INFO]["ids_same"].file == path
    other = update_names(updated, "localizations/fr/string/english.str", None, fs)
    assert other is updated


def test_minor_faction_names_define_galaxy_designs_at_their_key_path() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Gameplay.constants", CONSTANTS)
    _add(fs, LOW, "Galaxy/Elsewhere.constants", CONSTANTS)
    index = _chain(fs, "en")

    assert _provider(index, "GalaxyDesign", "defaulttech") == "GameInfo/Gameplay.constants"
    assert isinstance(index.resolve("GalaxyDesign", "TechMiners"), Found)
    assert isinstance(index.resolve("GalaxyDesign", "WrongLevel"), NotFound)
    assert isinstance(index.resolve("GalaxyDesign", "TechLoyalist"), NotFound)


def test_constants_and_scenario_definition_names_combine() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/Gameplay.constants", CONSTANTS)
    _add(fs, LOW, "GameInfo/GalaxyScenarioDef.galaxyScenarioDef", GSD.format(militia="Militia0"))
    index = _chain(fs, "en")

    for name in ("DefaultTech", "Pirate", "Militia0"):
        assert isinstance(index.resolve("GalaxyDesign", name), Found)


@pytest.mark.parametrize("name", ["NoOwner", "PlanetOwner", "noowner", "PLANETOWNER"])
def test_owner_tokens_are_always_valid(name: str) -> None:
    index = _chain(InMemoryFileSystem(), "en")

    result = index.resolve("GalaxyDesign", name)

    assert isinstance(result, Found) and isinstance(result.detail, BuiltinResolution)
    assert result.detail.token.requires is None
    assert isinstance(index.resolve("GalaxyDesign", name.upper() + "X"), NotFound)


def test_owner_tokens_are_not_valid_for_other_kinds() -> None:
    index = _chain(InMemoryFileSystem(), "en")

    assert isinstance(index.resolve("GalaxyTemplate", "NoOwner"), NotFound)
    assert isinstance(index.resolve("Entity", "PlanetOwner"), NotFound)


@pytest.mark.parametrize("name", ["Militia0", "militia7", "MILITIA19", "Militia100"])
def test_random_militia_needs_a_numbered_militia_player(name: str) -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia=name))
    index = _chain(fs, "en")

    result = index.resolve("GalaxyDesign", "RandomMilitia")

    assert isinstance(result, Found) and isinstance(result.detail, BuiltinResolution)


@pytest.mark.parametrize("name", ["Militia", "MilitiaX", "Militia_1", "AMilitia1"])
def test_random_militia_is_unresolved_without_a_numbered_militia_player(name: str) -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia=name))

    assert isinstance(_chain(fs, "en").resolve("GalaxyDesign", "RandomMilitia"), NotFound)


def test_random_militia_is_unresolved_when_no_player_defines_it() -> None:
    index = _chain(InMemoryFileSystem(), "en")

    assert isinstance(index.resolve("GalaxyDesign", "RandomMilitia"), NotFound)


def test_random_militia_is_undecided_on_an_incomplete_chain() -> None:
    index = _chain(InMemoryFileSystem(), "en", complete=False)

    assert isinstance(index.resolve("GalaxyDesign", "RandomMilitia"), Unknown)
    assert isinstance(index.resolve("GalaxyDesign", "NoOwner"), Found)


def test_random_militia_may_be_defined_by_a_lower_layer() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia="Militia3"))
    _add(fs, HIGH, "GameInfo/Other.txt")

    assert isinstance(_chain(fs, "en", (LOW, HIGH)).resolve("GalaxyDesign", "RandomMilitia"), Found)


def test_a_defined_design_beats_a_token_of_the_same_name() -> None:
    fs = InMemoryFileSystem()
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia="NoOwner"))

    result = _chain(fs, "en").resolve("GalaxyDesign", "noowner")

    assert isinstance(result, Found) and isinstance(result.detail, Resolution)


def test_adding_a_militia_player_revalidates_files_using_random_militia() -> None:
    fs = InMemoryFileSystem()
    layer = _layer(LOW, "low")
    before = index_names(build_layer_index(layer, fs), fs)
    _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia="Militia1"))
    after = index_names(build_layer_index(layer, fs), fs)
    token_user, other_user = Path("a.galaxy"), Path("b.galaxy")
    tracked = {
        token_user: frozenset({ResolvedRef(None, RefKind.GALAXY_DESIGN, "randommilitia")}),
        other_user: frozenset({ResolvedRef(None, RefKind.GALAXY_DESIGN, "noowner")}),
    }
    unrelated = IndexDelta(layer, frozenset({(RefKind.GALAXY_DESIGN, "pirate")}))

    delta = diff_layer_index(before, after)

    assert affected_files(tracked, [delta], [layer]) == {token_user}
    assert affected_files(tracked, [unrelated], [layer]) == frozenset()


def test_language_decides_which_sound_files_revalidate_dependents() -> None:
    layer = _layer(LOW, "low")
    ref = ResolvedRef(None, RefKind.SOUND_FILE, "boom", ".entity")
    tracked = {Path("a.entity"): frozenset({ref})}
    delta = IndexDelta(layer, files=frozenset({"localizations/de/sound/boom.ogg"}))

    assert affected_files(tracked, [delta], [layer], "de") == {Path("a.entity")}
    assert affected_files(tracked, [delta], [layer], "en") == frozenset()


def _owner_registry() -> object:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [{"node": "field", "name": "owner", "validation": "GalaxyDesign"}],
        }
    ]
    return load_registry_from_texts({"s.json": json.dumps({"structures": structures})})


@pytest.mark.parametrize(
    ("value", "defined", "codes"),
    [
        ("NoOwner", None, []),
        ("PlanetOwner", None, []),
        ("RandomMilitia", None, [dg.R010]),
        ("RandomMilitia", "Militia2", []),
        ("Tech", None, [dg.R010]),
    ],
)
def test_validator_reports_owner_tokens_by_their_rules(
    value: str, defined: str | None, codes: list[str]
) -> None:
    fs = InMemoryFileSystem()
    if defined is not None:
        _add(fs, LOW, "GameInfo/G.galaxyScenarioDef", GSD.format(militia=defined))
    index = _chain(fs, "en")
    path = Path("a.foo")
    ctx = ValidationContext(_owner_registry(), VERSION, path, lookup=index)  # type: ignore[arg-type]

    found = validate(parse(f'TXT\nowner "{value}"\n', path), ctx)

    assert [d.code for d in found] == codes


def test_layer_index_defaults_to_the_fallback_language() -> None:
    index = LayerIndex(_layer(LOW, "low"), "sha256:x")

    assert index.language == "en"
