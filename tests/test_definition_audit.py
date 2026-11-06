"""Validator results for the bundled Definition corrections.

Each test feeds the bundled Definitions a small synthetic file that reproduces
a real shape (names are made up; no game text is copied) and one or more shapes
the corrected Definitions must still reject. The evidence behind every
correction is in ``PROVENANCE.json`` and the registry level checks are in
``test_bundled_definitions.py``.

Shapes covered:

* ``.starscapedata``: decimal keys and ``starTextureName:0`` to ``:9`` quoted.
* ``.galaxy``: ``versionNumber`` first; random-map ``starCount`` at the top
  level or inside ``randomizerParams``; planet ``owner`` ``P0`` to ``P5``.
* ``.constants``: the Rebellion193 ``outlawSectorsData`` format.
* ``.randomeventdefs``: ``spawnType`` values and ``racialBuffCount`` followed
  by ``race``/``buff`` line pairs.
* ``Buff`` ``finishCondition`` ``AnyInstantActionWithTriggerTypeDone`` with an
  ``instantActionTriggerType`` line.
* ``EmpireWindowNode`` with ``hyperspaceNodeIcon``.
* ``ResearchSubject`` ``researchModifier`` runs and ``Player``
  ``raceRelationsModifier`` blocks, which need no Definition change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.parser import parse
from soase_validator.engine.registry import load_registry
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import GameVersion

_REGISTRY = load_registry()


def _run(
    name: str, lines: list[str], version: GameVersion = GameVersion.REBELLION_198
) -> list[tuple[str, int]]:
    """Validate synthetic lines and return ``(code, one-based line)`` pairs.

    Args:
        name: File name; its extension selects the root structure.
        lines: File lines; tabs indent.
        version: The Project's Game Version.

    Returns:
        The validator's findings. The parse must be clean.
    """
    path = Path(name)
    parsed = parse("\n".join(lines) + "\n", path, version)
    assert parsed.diagnostics == []
    diags = validate(parsed, ValidationContext(_REGISTRY, version, path))
    return [(d.code, d.range.start.line + 1) for d in diags]


_STARSCAPE = [
    "TXT",
    "starWidth 4.0",
    "starHeight 4.0",
    "starDistance 200.0",
    "starBlinksPerSecond 20.0",
    "starFadeDuration 0.15",
    'starTextureName:0 "ExampleStar0"',
    'starTextureName:1 "ExampleStar1"',
    *(f'starTextureName:{i} ""' for i in range(2, 10)),
]


def test_starscapedata_file_shape_is_valid() -> None:
    assert _run("Example.starscapedata", _STARSCAPE) == []
    structure = _REGISTRY.structure_for_extension(".starscapedata")
    assert structure is not None and structure.name == "StarscapeData"


def test_starscapedata_rejects_wrong_shapes() -> None:
    wrong_value = ['starWidth "wide"' if ln.startswith("starWidth") else ln for ln in _STARSCAPE]
    assert _run("Example.starscapedata", wrong_value) == [(dg.V050, 2)]
    entity_key = [*_STARSCAPE, 'resource "x"']
    assert _run("Example.starscapedata", entity_key) == [(dg.V020, len(entity_key))]
    eleventh = [*_STARSCAPE, 'starTextureName:10 ""']
    assert _run("Example.starscapedata", eleventh) == [(dg.V020, len(eleventh))]
    swapped = [_STARSCAPE[0], _STARSCAPE[2], _STARSCAPE[1], *_STARSCAPE[3:]]
    assert [code for code, _ in _run("Example.starscapedata", swapped)] == [dg.V060]


def _random_stars(depth: int, count: int = 1) -> list[str]:
    """Build the lines of a random-map star run with its count line at ``depth`` tabs."""

    def at(level: int, text: str) -> str:
        return "\t" * (depth + level) + text

    return [
        at(0, f"starCount {count}"),
        at(1, "star"),
        at(2, 'type "RandomNonGreenStar"'),
        at(2, "radius 75"),
        at(2, "connectionStarRadiusRange 0.5"),
        at(2, "connectionChance 0.75"),
        at(2, "maxPlayerCount 0"),
        at(2, "ringCount 1"),
        at(2, "ring"),
        at(3, "starRadiusRange"),
        at(4, "minPercentage 0.5"),
        at(4, "maxPercentage 0.7"),
        at(3, "militiaColonizationPerc 0"),
        at(3, "planetGroupCount 1"),
        at(3, "planetGroup"),
        at(4, "minCount 7"),
        at(4, "maxCount 7"),
        at(4, "planetTypeCount 1"),
        at(4, 'planetType "RandomTrue"'),
    ]


_RANDOM_HEAD = [
    "TXT",
    "versionNumber 193",
    "isBrowsable FALSE",
    "useRandomGenerator TRUE",
    "randomizerParams",
    "\tstarPosOffsetRange",
    "\t\tminPercentage 1.5",
    "\t\tmaxPercentage 2.0",
]


def test_random_map_star_run_after_randomizer_params_is_valid() -> None:
    """Accept ``starCount`` at the top level of a random-map galaxy."""
    assert _run("Example.galaxy", _RANDOM_HEAD + _random_stars(0)) == []


def test_random_map_star_run_inside_randomizer_params_is_valid() -> None:
    """Accept ``starCount`` inside ``randomizerParams``."""
    assert _run("Example.galaxy", _RANDOM_HEAD + _random_stars(1)) == []


@pytest.mark.parametrize("depth", [0, 1])
def test_random_map_star_run_still_checks_its_content(depth: int) -> None:
    lines = _RANDOM_HEAD + _random_stars(depth, count=2)
    assert [code for code, _ in _run("Example.galaxy", lines)] == [dg.V030]
    unknown = _RANDOM_HEAD + _random_stars(depth)
    unknown.insert(len(_RANDOM_HEAD) + 4, "\t" * (depth + 2) + "bogus 1")
    assert [code for code, _ in _run("Example.galaxy", unknown)] == [dg.V020]


def test_version_number_is_the_first_galaxy_key() -> None:
    assert _run("Example.galaxy", ["TXT", "versionNumber 193", "isBrowsable TRUE"]) == []
    quoted = ["TXT", 'versionNumber "193"', "isBrowsable TRUE"]
    assert _run("Example.galaxy", quoted) == [(dg.V050, 2)]
    late = ["TXT", "isBrowsable TRUE", "versionNumber 193"]
    assert [code for code, _ in _run("Example.galaxy", late)] == [dg.V060]


def _fixed_galaxy(owner: str) -> list[str]:
    return [
        "TXT",
        "versionNumber 193",
        "useRandomGenerator FALSE",
        "galaxyWidth 1920.000000",
        "galaxyHeight 1104.000000",
        "nextStarNameUniqueId 1",
        "nextPlanetNameUniqueId 1",
        "triggerCount 0",
        "starCount 1",
        "star",
        '\tdesignName "Star0"',
        '\tinGameName ""',
        '\ttype "RandomNonGreenStar"',
        "\tpos [ 244 , 204 ]",
        "\tradius 100.000000",
        "\tplanetCount 1",
        "\tplanet",
        '\t\tdesignName "Planet0"',
        '\t\tinGameName ""',
        '\t\ttype "TerranHome"',
        "\t\tpos [ 144 , 204 ]",
        f'\t\towner "{owner}"',
        "\t\tisHomePlanet FALSE",
        "\tconnectionCount 0",
        "interStarConnectionCount 0",
        "playerCount 0",
        "templates 0",
    ]


def _fixed_galaxy_with_player(owner: str, player: str) -> list[str]:
    lines = _fixed_galaxy(owner)
    player_count = lines.index("playerCount 0")
    lines[player_count] = "playerCount 1"
    lines[player_count + 1 : player_count + 1] = ["player", f'\tdesignName "{player}"']
    return lines


@pytest.mark.parametrize("owner", ["", "PlanetOwner", "NoOwner", "Pirate", "RandomMilitia"])
def test_fixed_planet_owner_values_are_accepted(owner: str) -> None:
    assert _run("Example.galaxy", _fixed_galaxy(owner)) == []


@pytest.mark.parametrize("owner", ["Player1", "NewPlayer3", "P0", "P3", "P5"])
def test_planet_owner_naming_a_declared_player_is_accepted(owner: str) -> None:
    assert _run("Example.galaxy", _fixed_galaxy_with_player(owner, owner)) == []


@pytest.mark.parametrize("owner", ["Player1", "P6", "p0", "Neutral"])
def test_planet_owner_naming_no_declared_player_is_rejected(owner: str) -> None:
    assert _run("Example.galaxy", _fixed_galaxy(owner)) == [(dg.V050, 22)]


def test_planet_owner_one_level_too_shallow_is_still_reported() -> None:
    """Report a planet ``owner`` written one level too shallow (design.md)."""
    lines = _fixed_galaxy("Player1")
    lines[21] = lines[21].removeprefix("\t")
    codes = {code for code, _ in _run("Example.galaxy", lines)}
    assert dg.V080 in codes


_OUTLAW = [
    "\toutlawSectorsData",
    "\t\tnpcIconOffset:Mesh",
    "\t\t\txOffset 0",
    "\t\t\tyOffset -35",
    "\t\tnpcIconOffset:MainViewIcon",
    "\t\t\txOffset 0",
    "\t\t\tyOffset -10",
    "\t\tnpcIconOffset:HUDIcon",
    "\t\t\txOffset -9",
    "\t\t\tyOffset -9",
    "\t\tnpcIconOffset:PlanetIcon",
    "\t\t\txOffset 0",
    "\t\t\tyOffset -52",
    '\t\toutlawSpawnShipsType "MatchPlayerRace"',
    "\t\tnumOutlawSpawnShipsOptionsCount 1",
    "\t\toutlawSpawnShipsOptions",
    '\t\t\traceEntityName "PlayerExampleRace"',
    "\t\t\tspawnShips",
    "\t\t\t\tminFleetPoints 20.000000",
    "\t\t\t\tmaxFleetPoints 20.000000",
    "\t\t\t\trequiredShipCount 0",
    "\t\t\t\trandomShipCount 1",
    "\t\t\t\trandomShip",
    '\t\t\t\t\ttype "FrigateExample"',
    "\t\t\t\t\tweight 4",
    "\t\tbaseFleetCapacity 10.000000",
]
_OUTLAW_185 = [
    "\toutlawSectorsData",
    "\t\tmilitiaMainViewXOffsetScalar 1.000000",
    "\t\tbaseFleetCapacity 10.000000",
]


def test_rebellion_193_outlaw_sectors_format_is_valid_at_194() -> None:
    lines = ["TXT2", "SinsArchiveVersion 194", "GameplayConstants", *_OUTLAW]
    assert _run("Example.constants", lines) == []


def test_rebellion_185_outlaw_sectors_format_stays_valid_only_at_185() -> None:
    old = ["TXT", "GameplayConstants", *_OUTLAW_185]
    assert _run("Example.constants", old, GameVersion.REBELLION_185) == []
    assert [c for c, _ in _run("Example.constants", old, GameVersion.REBELLION_198)] == [dg.V020]
    new = ["TXT", "GameplayConstants", *_OUTLAW[:4]]
    assert {c for c, _ in _run("Example.constants", new, GameVersion.REBELLION_185)} == {dg.V020}


def test_outlaw_sectors_content_is_checked() -> None:
    bad = ["TXT2", "SinsArchiveVersion 194", "GameplayConstants", *_OUTLAW]
    bad[3 + 14] = "\t\tnumOutlawSpawnShipsOptionsCount 2"
    assert [c for c, _ in _run("Example.constants", bad)] == [dg.V030]
    bad = ["TXT2", "SinsArchiveVersion 194", "GameplayConstants", *_OUTLAW]
    bad[3 + 13] = '\t\toutlawSpawnShipsType "Random"'
    assert [c for c, _ in _run("Example.constants", bad)] == [dg.V050]


def _event(spawn: list[str], tail: list[str]) -> list[str]:
    return [
        "\trandomEventDef",
        '\t\tid "EXAMPLE"',
        '\t\tnameID "IDS_EXAMPLE_NAME"',
        '\t\twarningID "IDS_EXAMPLE_WARNING"',
        *spawn,
        '\t\tplayerOwnerType "Rebel"',
        '\t\tspawnLocation "TriggerLocation"',
        "\t\texcludedSpawnLocationCount 0",
        *tail,
        "\t\tspawnWeight 1.0",
    ]


_TRIGGER = ['\t\tspawnRequirement "TriggerCultureFlip"', "\t\ttriggerWeight 0.1"]
_PROJECTILE = [
    '\t\tspawnType "Projectile"',
    '\t\tprojectileTarget "RandomConnectedLocation"',
    '\t\tspawnEntity "ExampleProjectile"',
]
_RACIAL = [
    '\t\tspawnType "RacialBuffAtLocation"',
    "\t\tracialBuffCount 2",
    '\t\t\trace "IDS_RACE_A"',
    '\t\t\tbuff "ExampleBuffA"',
    '\t\t\trace "IDS_RACE_B"',
    '\t\t\tbuff "ExampleBuffB"',
]


def test_random_event_spawn_types_and_racial_buff_pairs_are_valid() -> None:
    lines = [
        "TXT",
        "randomEventDefCount 3",
        *_event(_PROJECTILE, _TRIGGER),
        *_event(_RACIAL, _TRIGGER),
        *_event(['\t\tspawnType "BuffAtLocation"', '\t\tspawnEntity "ExampleBuff"'], _TRIGGER),
    ]
    assert _run("Example.randomeventdefs", lines) == []
    periodic = [
        '\t\tspawnType "PeriodicBuffAtLocation"',
        '\t\tspawnEntity "ExampleBuff"',
        "\t\tduration 300.0",
        "\t\tperiod 5.0",
    ]
    lines = ["TXT", "randomEventDefCount 1", *_event(periodic, _TRIGGER)]
    assert _run("Example.randomeventdefs", lines) == []


def test_random_event_spawn_type_rejects_other_enumerations_and_old_versions() -> None:
    other = ["TXT", "randomEventDefCount 1", *_event(['\t\tspawnType "RandomFromUp"'], _TRIGGER)]
    assert [(c, ln) for c, ln in _run("Example.randomeventdefs", other)] == [(dg.V050, 7)]
    projectile = ["TXT", "randomEventDefCount 1", *_event(_PROJECTILE, _TRIGGER)]
    gated = _run("Example.randomeventdefs", projectile, GameVersion.DIPLOMACY)
    assert (dg.V050, 7) in gated


def test_racial_buff_count_must_match_the_pairs() -> None:
    wrong = [ln.replace("racialBuffCount 2", "racialBuffCount 3") for ln in _RACIAL]
    lines = ["TXT", "randomEventDefCount 1", *_event(wrong, _TRIGGER)]
    assert [c for c, _ in _run("Example.randomeventdefs", lines)] == [dg.V030]
    wrapped = [
        '\t\tspawnType "RacialBuffAtLocation"',
        "\t\tracialBuffCount 1",
        "\t\t\tracialBuff",
        '\t\t\t\trace "IDS_RACE_A"',
    ]
    lines = ["TXT", "randomEventDefCount 1", *_event(wrapped, _TRIGGER)]
    assert dg.V020 in {c for c, _ in _run("Example.randomeventdefs", lines)}


def _buff(finish: list[str]) -> list[str]:
    return [
        "TXT2",
        "SinsArchiveVersion 194",
        'entityType "Buff"',
        'onReapplyDuplicateType "PrioritizeNewBuffs"',
        'buffStackingLimitType "ForAllPlayers"',
        "stackingLimit 1",
        "allowFirstSpawnerToStack FALSE",
        'buffExclusivityForAIType "ExclusiveForAllPlayers"',
        "isInterruptable FALSE",
        "isChannelling FALSE",
        "numInstantActions 0",
        "numPeriodicActions 0",
        "numOverTimeActions 0",
        "numEntityModifiers 0",
        "numEntityBoolModifiers 0",
        "numFinishConditions 1",
        "finishCondition",
        *finish,
    ]


def test_finish_condition_with_trigger_type_line_is_valid() -> None:
    finish = [
        '\tfinishConditionType "AnyInstantActionWithTriggerTypeDone"',
        '\tinstantActionTriggerType "OnColonizeAbilityUsed"',
    ]
    assert _run("Example.entity", _buff(finish)) == []


def test_finish_condition_trigger_type_is_checked_and_not_shared() -> None:
    bad_value = [
        '\tfinishConditionType "AnyInstantActionWithTriggerTypeDone"',
        '\tinstantActionTriggerType "NotATrigger"',
    ]
    assert _run("Example.entity", _buff(bad_value)) == [(dg.V050, 19)]
    other_type = [
        '\tfinishConditionType "AbilityUsed"',
        '\tinstantActionTriggerType "OnColonizeAbilityUsed"',
    ]
    assert _run("Example.entity", _buff(other_type)) == [(dg.V020, 19)]
    assert _run("Example.entity", _buff(['\tfinishConditionType "AbilityUsed"'])) == []


def test_empire_window_node_hyperspace_icon_is_valid_in_rebellion() -> None:
    lines = [
        "TXT2",
        "SinsArchiveVersion 194",
        'entityType "EmpireWindowNode"',
        'hyperspaceNodeIcon "ExampleIcon"',
    ]
    assert _run("Example.entity", lines) == []
    assert _run("Example.entity", [*lines, "bogus 1"]) == [(dg.V020, 5)]


_RESEARCH = [
    "TXT2",
    "SinsArchiveVersion 194",
    'entityType "ResearchSubject"',
    "researchBoolModifiers 2",
    "researchModifier",
    '\tmodifierType "AllowMissionOffers"',
    "researchModifier",
    '\tmodifierType "PlanetIsColonizable"',
    '\tlinkedPlanetType "Greenhouse"',
    "researchFloatModifiers 3",
    "researchModifier",
    '\tmodifierType "WeaponDamageAdjustment"',
    "\tbaseValue 0.000000",
    "\tperLevelValue 0.200000",
    '\tlinkedWeaponClass "WAVE"',
    "researchModifier",
    '\tmodifierType "PlanetUpgradeCostAdjustment"',
    "\tbaseValue 0.000000",
    "\tperLevelValue 0.250000",
    '\tlinkedPlanetUpgradeType "ArtifactLevel"',
    "researchModifier",
    '\tmodifierType "PlanetPopulationCapAdjustment"',
    "\tbaseValue 0.000000",
    "\tperLevelValue 0.250000",
    '\tlinkedPlanetType "Invalid"',
]


def test_research_modifier_runs_are_told_apart_by_their_count_line() -> None:
    """Accept bool and float runs that share the repeat key ``researchModifier``."""
    assert _run("Example.entity", _RESEARCH) == []


def test_research_modifier_rejects_wrong_shapes() -> None:
    swapped = [ln.replace("researchBoolModifiers 2", "researchBoolModifiers 3") for ln in _RESEARCH]
    assert dg.V030 in {c for c, _ in _run("Example.entity", swapped)}
    unknown = _RESEARCH.copy()
    unknown.insert(13, "\tbogusKey 1")
    assert _run("Example.entity", unknown) == [(dg.V020, 14)]
    bad_type = [ln.replace("WeaponDamageAdjustment", "NotAModifier") for ln in _RESEARCH]
    assert _run("Example.entity", bad_type)[0] == (dg.V050, 12)
    float_name_in_bool_run = _RESEARCH.copy()
    float_name_in_bool_run[5] = '\tmodifierType "WeaponDamageAdjustment"'
    assert _run("Example.entity", float_name_in_bool_run)[0] == (dg.V050, 6)


_PLAYER = [
    "TXT2",
    "SinsArchiveVersion 194",
    'entityType "Player"',
    "raceRelationsModCount 2",
    "raceRelationsModifier",
    '\traceNameID "IDS_RACE_A"',
    "\tmodifierMin -1.500000",
    "\tmodifierMax -1.000000",
    "\tfactionRelationsModCount 1",
    "\tfactionRelationsModifier",
    '\t\tfactionNameID "IDS_FACTION_A"',
    '\t\totherFactionNameID "IDS_FACTION_B"',
    "\t\tmodifierMin -5.000000",
    "\t\tmodifierMax -5.000000",
    "raceRelationsModifier",
    '\traceNameID "IDS_RACE_B"',
    "\tmodifierMin -1.000000",
    "\tmodifierMax -0.500000",
    "\tfactionRelationsModCount 0",
]


def test_race_relations_modifier_blocks_are_valid_in_rebellion() -> None:
    """Apply only the Rebellion field when two gated iterative fields share a key."""
    assert _run("Example.entity", _PLAYER) == []


def test_race_relations_modifier_rejects_wrong_shapes() -> None:
    unknown = _PLAYER.copy()
    unknown.insert(6, "\tbogusKey 1")
    assert _run("Example.entity", unknown) == [(dg.V020, 7)]
    text = [ln.replace("modifierMin -1.500000", 'modifierMin "low"') for ln in _PLAYER]
    assert _run("Example.entity", text) == [(dg.V050, 7)]
    short = [ln.replace("raceRelationsModCount 2", "raceRelationsModCount 3") for ln in _PLAYER]
    assert [c for c, _ in _run("Example.entity", short)] == [dg.V030]
