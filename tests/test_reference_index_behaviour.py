"""End-to-end tests of reference resolution over a resolved Chain.

Each test builds small synthetic Layer trees under ``tmp_path``, resolves the
Chain from settings, builds the merged index and validates a file against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.chain import Chain, resolve_chain
from soase_validator.engine.chainindex import (
    CONFIGURATION_HINT,
    ChainIndex,
    build_chain_index,
    limited_checks_notice,
)
from soase_validator.engine.config import ManifestPrefs, ResolvedSettings
from soase_validator.engine.deptracker import RecordingLookup
from soase_validator.engine.layercache import SCHEMA_VERSION, LayerCache
from soase_validator.engine.model import Diagnostic, Severity
from soase_validator.engine.parser import parse
from soase_validator.engine.primitives import NumericPrefs
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import DEFAULT_REBELLION

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'


def _settings(
    layers: tuple[Path | str, ...] = (),
    mod_roots: tuple[Path, ...] = (),
    reference_root: Path | None = None,
    aliases: dict[str, Path] | None = None,
    *,
    suppress_limited_notice: bool = False,
) -> ResolvedSettings:
    roots = {DEFAULT_REBELLION: reference_root} if reference_root else {}
    return ResolvedSettings(
        game_version=DEFAULT_REBELLION,
        reference_roots=roots,
        mod_roots=mod_roots,
        layer_specs=tuple(str(layer) for layer in layers),
        aliases=aliases or {},
        disabled_codes=frozenset(),
        numeric=NumericPrefs(),
        manifest=ManifestPrefs(),
        report_overrides=False,
        suppress_limited_notice=suppress_limited_notice,
        project_file=None,
        sources={},
        problems=(),
    )


def _layer(root: Path, *brushes: str) -> Path:
    window = root / "Window"
    window.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(brushes):
        (window / f"b{i}.brushes").write_text(BRUSHES.format(name=name), encoding="utf-8")
    return root


def _game(root: Path, *brushes: str) -> Path:
    (root / "GameInfo").mkdir(parents=True, exist_ok=True)
    return _layer(root, *brushes)


def _index(chain: Chain, cache: LayerCache | None = None) -> ChainIndex:
    cache = LayerCache(use_disk=False) if cache is None else cache
    return build_chain_index(chain, DEFAULT_REBELLION, cache)


def _validate(index: ChainIndex, name: str) -> list[Diagnostic]:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [{"node": "field", "name": "b", "validation": "Brush"}],
        }
    ]
    registry = load_registry_from_texts({"s.json": json.dumps({"structures": structures})})
    path = Path("a.foo")
    ctx = ValidationContext(registry, DEFAULT_REBELLION, path, lookup=index)
    return validate(parse(f'TXT\nb "{name}"\n', path), ctx)


def _notice(chain: Chain, settings: ResolvedSettings) -> list[Diagnostic]:
    return limited_checks_notice(chain, Path("a.foo"), suppressed=settings.suppress_limited_notice)


def test_incomplete_chain_notice_names_each_missing_layer_and_how_to_configure(
    tmp_path: Path,
) -> None:
    game = _game(tmp_path / "game")
    gone = tmp_path / "gone"
    not_game = tmp_path / "not-game"
    not_game.mkdir()
    project = _layer(tmp_path / "project")
    settings = _settings((gone, not_game), (project,), game)
    chain = resolve_chain(settings)

    notice = _notice(chain, settings)

    assert not chain.complete
    assert len(notice) == 1
    only = notice[0]
    assert only.code == dg.C030 and only.severity is Severity.INFO
    assert f"gone is missing ({gone})" in only.message
    assert "not-game" not in only.message
    assert CONFIGURATION_HINT in only.message


def test_notice_names_an_unusable_game_layer_and_an_undefined_alias(tmp_path: Path) -> None:
    empty_game = tmp_path / "game"
    empty_game.mkdir()
    project = _layer(tmp_path / "project")
    settings = _settings(("@e4x",), (project,), empty_game)
    chain = resolve_chain(settings)

    message = _notice(chain, settings)[0].message

    assert f"game is unusable ({empty_game})" in message
    assert "@e4x is missing" in message


def test_incomplete_chain_reports_no_unresolved_reference_but_resolves_usable_layers(
    tmp_path: Path,
) -> None:
    game = _game(tmp_path / "game", "GameBrush")
    project = _layer(tmp_path / "project", "ModBrush")
    chain = resolve_chain(_settings((tmp_path / "gone",), (project,), game))
    index = _index(chain)

    assert not chain.complete
    assert _validate(index, "NotAnywhere") == []
    assert _validate(index, "gamebrush") == []
    assert _validate(index, "MODBRUSH") == []


def test_notice_is_suppressed_by_configuration(tmp_path: Path) -> None:
    project = _layer(tmp_path / "project")
    settings = _settings((tmp_path / "gone",), (project,), suppress_limited_notice=True)
    chain = resolve_chain(settings)

    assert not chain.complete
    assert _notice(chain, settings) == []
    assert len(_notice(chain, _settings((tmp_path / "gone",), (project,)))) == 1


def test_nonexistent_layer_gives_one_warning_naming_the_path_and_chain_continues(
    tmp_path: Path,
) -> None:
    gone = tmp_path / "gone"
    parent = _layer(tmp_path / "parent", "ParentBrush")
    project = _layer(tmp_path / "project", "ModBrush")
    chain = resolve_chain(_settings((gone, parent), (project,)))

    assert [p.code for p in chain.problems] == [dg.C020]
    assert dg.CODE_CATALOGUE[dg.C020].severity is Severity.WARNING
    assert chain.problems[0].path == gone
    assert "gone" in chain.problems[0].message and str(gone) in chain.problems[0].message
    assert [layer.status for layer in chain.layers] == ["missing", "ok", "ok"]
    assert _validate(_index(chain), "parentbrush") == []


def test_reference_root_that_is_not_game_data_gives_one_warning_and_is_unusable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "docs"
    (root / "Notes").mkdir(parents=True)
    project = _layer(tmp_path / "project", "ModBrush")
    chain = resolve_chain(_settings((), (project,), root))

    assert [p.code for p in chain.problems] == [dg.C020]
    assert chain.problems[0].path == root
    assert "unusable" in chain.problems[0].message
    assert chain.layers[0].kind == "game" and chain.layers[0].status == "unusable"
    assert not chain.complete
    assert [i.layer.name for i in _index(chain).indexes] == ["project"]


def test_highest_layer_provides_a_name_and_the_next_lower_one_is_overridden(
    tmp_path: Path,
) -> None:
    game = _game(tmp_path / "game", "Shared", "OnlyGame")
    parent = _layer(tmp_path / "parent", "SHARED", "OnlyParent")
    project = _layer(tmp_path / "project", "shared")
    index = _index(resolve_chain(_settings((parent,), (project,), game)))

    top = index.lookup("Brush", "Shared")
    assert top is not None and top.layer.name == "project"
    assert top.overrides is not None and top.overrides.name == "parent"

    middle = index.lookup("Brush", "onlyparent")
    assert middle is not None and middle.layer.name == "parent" and middle.overrides is None

    lowest = index.lookup("Brush", "ONLYGAME")
    assert lowest is not None and lowest.layer.kind == "game" and lowest.overrides is None


def test_override_skips_layers_that_do_not_provide_the_name(tmp_path: Path) -> None:
    game = _game(tmp_path / "game", "Shared")
    parent = _layer(tmp_path / "parent", "Other")
    project = _layer(tmp_path / "project", "Shared")
    index = _index(resolve_chain(_settings((parent,), (project,), game)))

    hit = index.lookup("Brush", "shared")

    assert hit is not None and hit.layer.name == "project"
    assert hit.overrides is not None and hit.overrides.kind == "game"


def test_override_in_an_unusable_layer_is_not_reported(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    project = _layer(tmp_path / "project", "Shared")
    index = _index(resolve_chain(_settings((gone,), (project,))))

    hit = index.lookup("Brush", "Shared")

    assert hit is not None and hit.overrides is None


def _cached_chain(tmp_path: Path) -> tuple[Chain, Path]:
    parent = _layer(tmp_path / "parent", "ParentBrush")
    project = _layer(tmp_path / "project", "ModBrush")
    return resolve_chain(_settings((parent,), (project,))), tmp_path / "cache"


@pytest.mark.parametrize(
    "damage",
    [
        "{not json",
        "",
        "[]",
        json.dumps({"schema": 999}),
        json.dumps({"schema": SCHEMA_VERSION, "signature": "x"}),
    ],
    ids=["truncated", "empty", "wrong-type", "foreign-schema", "missing-fields"],
)
def test_damaged_cache_file_is_replaced_and_references_still_resolve(
    tmp_path: Path, damage: str
) -> None:
    chain, cache_dir = _cached_chain(tmp_path)
    cache = LayerCache(cache_dir)
    _index(chain, cache)
    files = sorted(cache_dir.glob("*.json"))
    assert len(files) == 2
    for file in files:
        file.write_text(damage, encoding="utf-8")

    index = _index(chain, LayerCache(cache_dir))

    assert _validate(index, "parentbrush") == []
    assert [d.code for d in _validate(index, "Gone")] == [dg.R010]
    for file in files:
        assert json.loads(file.read_text(encoding="utf-8"))["schema"] == SCHEMA_VERSION


def test_cache_is_rebuilt_when_a_layer_file_changes_after_a_valid_cache(
    tmp_path: Path,
) -> None:
    chain, cache_dir = _cached_chain(tmp_path)
    _index(chain, LayerCache(cache_dir))
    parent = chain.layers[0].path
    (parent / "Window" / "extra.brushes").write_text(BRUSHES.format(name="Fresh"), encoding="utf-8")

    index = _index(chain, LayerCache(cache_dir))

    assert _validate(index, "fresh") == []


def test_no_reference_root_project_only_chain_is_complete_and_reports_unresolved(
    tmp_path: Path,
) -> None:
    project = _layer(tmp_path / "project", "ModBrush")
    settings = _settings((), (project,))
    chain = resolve_chain(settings)
    index = _index(chain)

    assert chain.complete and chain.problems == ()
    assert all(layer.kind != "game" for layer in chain.layers)
    assert _notice(chain, settings) == []
    assert _validate(index, "modbrush") == []
    unresolved = _validate(index, "Gone")
    assert [d.code for d in unresolved] == [dg.R010]
    assert "Brush" in unresolved[0].message and "Gone" in unresolved[0].message


def test_no_reference_root_with_declared_usable_layers_resolves_against_them(
    tmp_path: Path,
) -> None:
    parent = _layer(tmp_path / "parent", "ParentBrush")
    project = _layer(tmp_path / "project", "ModBrush")
    settings = _settings((parent,), (project,))
    chain = resolve_chain(settings)
    index = _index(chain)

    assert chain.complete
    assert _notice(chain, settings) == []
    assert _validate(index, "ParentBrush") == []
    assert _validate(index, "ModBrush") == []
    assert [d.code for d in _validate(index, "Gone")] == [dg.R010]


def test_no_reference_root_and_no_layers_at_all_is_complete_with_no_notice() -> None:
    settings = _settings()
    chain = resolve_chain(settings)

    assert chain.complete and chain.layers == ()
    assert _notice(chain, settings) == []


GSD_TEXT = (
    "TXT2\nSinsArchiveVersion 193\n"
    'planetType\n\tdesignName "Desert"\n\torbitBodyTypeCount 0\n'
    'planetItemsTemplate\n\ttemplateName "Common"\n\tsubTemplates 0\n\tgroups 0\n'
)

GALAXY_STRUCTURES = [
    {
        "name": "Galaxy",
        "extension": ".galaxy",
        "children": [
            {"node": "field", "name": "planetType", "validation": "GalaxyDesign"},
            {"node": "field", "name": "templateRef", "validation": "GalaxyTemplate"},
            {"node": "structure_reference", "name": "player", "structure": "PlayerBlock"},
            {"node": "structure_reference", "name": "template", "structure": "TemplateBlock"},
        ],
    },
    {
        "name": "PlayerBlock",
        "children": [{"node": "field", "name": "designName", "validation": "Any"}],
    },
    {
        "name": "TemplateBlock",
        "children": [{"node": "field", "name": "templateName", "validation": "Any"}],
    },
    {
        "name": "Other",
        "extension": ".other",
        "children": [
            {"node": "field", "name": "planetType", "validation": "GalaxyDesign"},
            {"node": "structure_reference", "name": "player", "structure": "PlayerBlock"},
        ],
    },
]


def _galaxy_diagnostics(index: ChainIndex, name: str, text: str, suffix: str) -> list[str]:
    registry = load_registry_from_texts({"s.json": json.dumps({"structures": GALAXY_STRUCTURES})})
    path = Path(f"a{suffix}")
    ctx = ValidationContext(registry, DEFAULT_REBELLION, path, lookup=index)
    return [d.code for d in validate(parse(text, path), ctx)]


def _scenario_chain(tmp_path: Path) -> ChainIndex:
    game = _game(tmp_path / "game")
    (game / "GameInfo" / "GalaxyScenarioDef.galaxyScenarioDef").write_text(
        GSD_TEXT, encoding="utf-8"
    )
    return _index(resolve_chain(_settings((), (), game)))


def test_scenario_definition_names_resolve_in_every_file_type(tmp_path: Path) -> None:
    index = _scenario_chain(tmp_path)

    for suffix in (".galaxy", ".other"):
        assert _galaxy_diagnostics(index, "", 'TXT\nplanetType "DESERT"\n', suffix) == []
        assert _galaxy_diagnostics(index, "", 'TXT\nplanetType "Gone"\n', suffix) == [dg.R010]
    assert _galaxy_diagnostics(index, "", 'TXT\ntemplateRef "common"\n', ".galaxy") == []


def test_names_declared_in_a_galaxy_file_resolve_only_inside_that_file(tmp_path: Path) -> None:
    index = _scenario_chain(tmp_path)
    declared = (
        'TXT\nplanetType "mine"\ntemplateRef "LocalTemplate"\n'
        'player\n\tdesignName "Mine"\ntemplate\n\ttemplateName "LOCALTEMPLATE"\n'
    )

    assert _galaxy_diagnostics(index, "", declared, ".galaxy") == []
    assert _galaxy_diagnostics(index, "", 'TXT\nplanetType "Mine"\n', ".galaxy") == [dg.R010]
    assert _galaxy_diagnostics(index, "", 'TXT\ntemplateRef "LocalTemplate"\n', ".galaxy") == [
        dg.R010
    ]
    other = 'TXT\nplanetType "Mine"\nplayer\n\tdesignName "Mine"\n'
    assert _galaxy_diagnostics(index, "", other, ".other") == [dg.R010]


def test_names_declared_in_a_galaxy_file_are_not_asked_of_the_lookup(tmp_path: Path) -> None:
    index = _scenario_chain(tmp_path)
    recorder = RecordingLookup(index)
    registry = load_registry_from_texts({"s.json": json.dumps({"structures": GALAXY_STRUCTURES})})
    path = Path("a.galaxy")
    ctx = ValidationContext(registry, DEFAULT_REBELLION, path, lookup=recorder)
    text = 'TXT\nplanetType "Mine"\nplayer\n\tdesignName "Mine"\n'

    validate(parse(text, path), ctx)

    assert recorder.references == frozenset()
