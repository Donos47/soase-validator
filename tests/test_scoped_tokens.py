"""Tests for race tokens that are valid only as a QuickStart condition param."""

from __future__ import annotations

from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.chain import Chain, Layer
from soase_validator.engine.chainindex import build_chain_index
from soase_validator.engine.deptracker import RecordingLookup
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.parser import parse
from soase_validator.engine.refindex import InMemoryFileSystem
from soase_validator.engine.registry import load_registry
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import GameVersion

VERSION = GameVersion.REBELLION_198
LOW = Path("/low")
GSD = (
    "TXT2\nSinsArchiveVersion 194\n"
    'playerType\n\tdesignName "TechLoyalist"\n'
    'minorFactionPlayerDef\n\tname "Other"\n'
)

GALAXY = (
    "TXT\nversionNumber 193\n"
    "templates 1\n"
    "template\n"
    '\ttemplateName "T"\n'
    "\tsubTemplates 0\n"
    "\tgroups 1\n"
    "\tgroup\n"
    "\t\tcondition\n"
    '\t\t\ttype "{type}"\n'
    '\t\t\tparam "{param}"\n'
    '\t\towner "{owner}"\n'
    "\t\tcolonizeChance 100\n"
    "\t\titems 0\n"
)


def _validate(text: str, *, defined: bool = False) -> list[str]:
    fs = InMemoryFileSystem()
    if defined:
        fs.add_file(LOW / "GameInfo/G.galaxyScenarioDef", size=1, mtime_ns=1, text=GSD)
    layer = Layer("low", LOW, "mod", "ok")
    index = build_chain_index(Chain((layer,), True), VERSION, LayerCache(use_disk=False), fs)
    path = Path("a.galaxy")
    ctx = ValidationContext(load_registry(), VERSION, path, lookup=index)
    found = validate(parse(text, path), ctx)
    return [d.code for d in found if d.code == dg.R010]


def _galaxy(type_: str, param: str, owner: str = "PlanetOwner") -> str:
    return GALAXY.format(type=type_, param=param, owner=owner)


@pytest.mark.parametrize("name", ["Tech", "Psi", "Phase", "tech", "PSI", "pHaSe"])
def test_race_tokens_are_valid_as_a_quickstart_param(name: str) -> None:
    assert _validate(_galaxy("PlanetOwnerIsRaceQuickStart", name)) == []


@pytest.mark.parametrize("name", ["Tech", "Psi", "Phase"])
def test_race_tokens_are_unresolved_as_an_owner(name: str) -> None:
    text = _galaxy("PlanetOwnerIsRaceQuickStart", "Tech", owner=name)

    assert _validate(text) == [dg.R010]


@pytest.mark.parametrize(
    "type_", ["PlanetOwnerIsRaceNormalStart", "PlanetOwnerIsMinorFactionWithFactionName"]
)
def test_race_tokens_are_unresolved_for_other_condition_types(type_: str) -> None:
    assert _validate(_galaxy(type_, "Psi")) == [dg.R010]


def test_other_names_stay_unresolved_as_a_quickstart_param() -> None:
    assert _validate(_galaxy("PlanetOwnerIsRaceQuickStart", "Techs")) == [dg.R010]


def test_race_tokens_are_unresolved_in_another_file_type() -> None:
    fs = InMemoryFileSystem()
    layer = Layer("low", LOW, "mod", "ok")
    index = build_chain_index(Chain((layer,), True), VERSION, LayerCache(use_disk=False), fs)
    path = Path("a.galaxyScenarioDef")
    ctx = ValidationContext(load_registry(), VERSION, path, lookup=index)
    text = "TXT2\nSinsArchiveVersion 194\n" + _galaxy("PlanetOwnerIsRaceQuickStart", "Tech")[4:]

    found = validate(parse(text, path), ctx)

    assert [d.code for d in found if d.code == dg.R010] == []


def test_a_layer_design_of_the_same_name_still_resolves_and_is_tracked() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(
        LOW / "GameInfo/G.galaxyScenarioDef",
        size=1,
        mtime_ns=1,
        text='TXT2\nSinsArchiveVersion 194\nplayerType\n\tdesignName "tech"\n',
    )
    layer = Layer("low", LOW, "mod", "ok")
    index = build_chain_index(Chain((layer,), True), VERSION, LayerCache(use_disk=False), fs)
    recorder = RecordingLookup(index)
    path = Path("a.galaxy")
    ctx = ValidationContext(load_registry(), VERSION, path, lookup=recorder)  # type: ignore[arg-type]

    found = validate(parse(_galaxy("PlanetOwnerIsRaceQuickStart", "Tech"), path), ctx)

    assert [d.code for d in found if d.code == dg.R010] == []
    tech = [r for r in recorder.references if r.name == "tech"]
    assert [r.layer for r in tech] == [layer]


def test_a_token_resolved_without_a_layer_is_tracked_as_unprovided() -> None:
    fs = InMemoryFileSystem()
    layer = Layer("low", LOW, "mod", "ok")
    index = build_chain_index(Chain((layer,), True), VERSION, LayerCache(use_disk=False), fs)
    recorder = RecordingLookup(index)
    path = Path("a.galaxy")
    ctx = ValidationContext(load_registry(), VERSION, path, lookup=recorder)  # type: ignore[arg-type]

    validate(parse(_galaxy("PlanetOwnerIsRaceQuickStart", "Tech"), path), ctx)

    tech = [r for r in recorder.references if r.name == "tech"]
    assert [r.layer for r in tech] == [None]


def test_reference_root_galaxy_design_names_all_resolve(reference_root: Path) -> None:
    layer = Layer("game", reference_root, "game", "ok")
    index = build_chain_index(Chain((layer,), True), VERSION, LayerCache(use_disk=False))
    registry = load_registry()
    unresolved: list[str] = []
    for file in sorted(reference_root.rglob("*.galaxy")):
        path = Path(file.name)
        ctx = ValidationContext(registry, VERSION, path, lookup=index)
        found = validate(parse(file.read_text(encoding="utf-8", errors="replace"), path), ctx)
        unresolved += [
            d.message for d in found if d.code == dg.R010 and "GalaxyDesign" in d.message
        ]

    assert unresolved == []
