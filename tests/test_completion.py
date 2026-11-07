"""Unit tests for completion, hover and go-to-definition.

Definitions and mod trees are synthetic. Entity names come from files in the
standard ``GameInfo`` directory of each Layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine.chain import Chain, Layer
from soase_validator.engine.chainindex import ChainIndex, build_chain_index
from soase_validator.engine.completion import (
    KIND_ENTITY_TYPE,
    KIND_ENUM,
    KIND_KEY,
    KIND_REFERENCE,
    AssistContext,
    complete,
    entity_types,
    field_help,
    goto_definition,
    hover,
)
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.model import Position
from soase_validator.engine.registry import Registry, load_registry_from_texts
from soase_validator.engine.versions import GameVersion

REBELLION = GameVersion.REBELLION_198
FILE = Path("GameInfo/Ship.entity")
HEADER = 'TXT2\nSinsArchiveVersion 194\nentityType "Frigate"\n'

_STRUCTURES = {
    "structures": [
        {
            "name": "Frigate",
            "help": "A frigate.",
            "children": [
                {
                    "node": "field",
                    "name": "hullType",
                    "type": "HullKind",
                    "required": True,
                    "help": "Hull class.",
                },
                {"node": "field", "name": "targetEntity", "validation": "Entity"},
                {"node": "field", "name": "armed", "validation": "Boolean"},
                {
                    "node": "field",
                    "name": "shield",
                    "validation": "Decimal",
                    "version": "Rebellion",
                },
                {
                    "node": "condition_field",
                    "name": "mode",
                    "type": "ModeKind",
                    "branches": {
                        "Solo": [{"node": "field", "name": "soloOnly", "validation": "Integer"}],
                        "Pack": [{"node": "field", "name": "packOnly", "validation": "Integer"}],
                    },
                },
            ],
        },
        {"name": "Titan", "children": []},
    ]
}
_ENUMS = {
    "enums": [
        {
            "name": "entityType",
            "values": [
                "Frigate",
                {"name": "Titan", "version": "Rebellion", "help": "A titan."},
                {"name": "Orphan", "help": "No structure."},
            ],
        },
        {
            "name": "HullKind",
            "values": [
                {"name": "Light", "help": "A small hull."},
                {"name": "Heavy", "version": "Rebellion"},
                "Plain",
            ],
        },
        {"name": "ModeKind", "values": ["Solo", "Pack"]},
    ]
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Registry over the synthetic Definitions."""
    registry = load_registry_from_texts(
        {"s.json": json.dumps(_STRUCTURES), "enums.json": json.dumps(_ENUMS)}
    )
    assert registry.warnings == ()
    return registry


def _tree(root: Path, names: list[str]) -> Path:
    """Create empty entity files below ``root/GameInfo``."""
    (root / "GameInfo").mkdir(parents=True)
    for name in names:
        (root / "GameInfo" / f"{name}.entity").write_text("TXT\n", encoding="utf-8")
    return root


def _chain_index(tmp_path: Path, *, complete: bool = True) -> ChainIndex:
    """Index a two-Layer Chain: the game defines Ship and Dock, the project Ship and Yard."""
    low = _tree(tmp_path / "low", ["Ship", "Dock"])
    high = _tree(tmp_path / "high", ["Ship", "Yard"])
    layers = (Layer("low", low, "game", "ok"), Layer("high", high, "project", "ok"))
    if not complete:
        missing = Layer("gone", tmp_path / "gone", "mod", "missing")
        layers = (missing, *layers)
    return build_chain_index(Chain(layers, complete), REBELLION, LayerCache(use_disk=False))


def _cursor(marked: str) -> tuple[str, Position]:
    """Split a document at the ``|`` marker into text and cursor position."""
    before, after = marked.split("|")
    lines = before.split("\n")
    return before + after, Position(len(lines) - 1, len(lines[-1]))


def _complete(
    registry: Registry,
    marked: str,
    *,
    version: GameVersion = REBELLION,
    chain: ChainIndex | None = None,
):
    text, position = _cursor(marked)
    return complete(text, position, AssistContext(registry, version, FILE, chain))


def _labels(items) -> list[str]:
    return [item.label for item in items]


def test_entity_type_completion_lists_the_types_valid_for_the_version(registry: Registry) -> None:
    marked = 'TXT2\nSinsArchiveVersion 194\nentityType "|'

    items = _complete(registry, marked)
    assert _labels(items) == ["Frigate", "Titan"]
    assert {i.kind for i in items} == {KIND_ENTITY_TYPE}
    assert items[1].documentation == "A titan."
    assert _labels(_complete(registry, marked, version=GameVersion.VANILLA)) == ["Frigate"]


def test_entity_type_completion_filters_by_prefix_ignoring_case(registry: Registry) -> None:
    assert _labels(_complete(registry, 'TXT2\nentityType "ti|')) == ["Titan"]
    assert _labels(_complete(registry, 'TXT2\nentityType "zz|')) == []


def test_entity_types_lists_valid_members_for_a_version(registry: Registry) -> None:
    assert entity_types(registry, REBELLION) == ["Frigate", "Titan"]
    assert entity_types(registry, GameVersion.VANILLA) == ["Frigate"]


def test_key_completion_omits_present_keys_and_keeps_declared_order(registry: Registry) -> None:
    items = _complete(registry, f'{HEADER}hullType "Light"\n|')

    assert _labels(items) == ["targetEntity", "armed", "shield", "mode"]
    assert {i.kind for i in items} == {KIND_KEY}
    assert "shield" not in _labels(_complete(registry, f"{HEADER}|", version=GameVersion.VANILLA))


def test_key_completion_offers_entity_type_in_an_entity_file_without_one(
    registry: Registry,
) -> None:
    assert _labels(_complete(registry, "TXT2\n|")) == ["entityType"]


def test_key_completion_returns_documentation_and_filters_by_prefix(registry: Registry) -> None:
    items = _complete(registry, f"{HEADER}HU|")

    assert [(i.label, i.documentation) for i in items] == [("hullType", "Hull class.")]


def test_key_completion_uses_only_the_selected_condition_branch(registry: Registry) -> None:
    solo = _labels(_complete(registry, f'{HEADER}mode "Solo"\n|'))
    unset = _labels(_complete(registry, f"{HEADER}|"))

    assert "soloOnly" in solo
    assert "packOnly" not in solo
    assert "soloOnly" not in unset
    assert "packOnly" not in unset


def test_value_completion_returns_version_gated_enum_members_with_help(
    registry: Registry,
) -> None:
    items = _complete(registry, f'{HEADER}hullType "|')

    assert [(i.label, i.documentation) for i in items] == [
        ("Light", "A small hull."),
        ("Heavy", None),
        ("Plain", None),
    ]
    assert {i.kind for i in items} == {KIND_ENUM}
    older = _complete(registry, f'{HEADER}hullType "|', version=GameVersion.VANILLA)
    assert _labels(older) == ["Light", "Plain"]
    assert _labels(_complete(registry, f'{HEADER}hullType "p|')) == ["Plain"]


def test_value_completion_offers_boolean_members(registry: Registry) -> None:
    assert _labels(_complete(registry, f"{HEADER}armed |")) == ["TRUE", "FALSE"]
    assert _labels(_complete(registry, f"{HEADER}armed t|")) == ["TRUE"]


def test_value_completion_is_empty_after_a_complete_value(registry: Registry) -> None:
    assert _complete(registry, f'{HEADER}hullType "Light" |') == []


def test_reference_completion_lists_each_name_once_with_the_providing_layer(
    registry: Registry, tmp_path: Path
) -> None:
    chain = _chain_index(tmp_path)

    items = _complete(registry, f'{HEADER}targetEntity "|', chain=chain)

    assert [(i.label, i.detail, i.kind) for i in items] == [
        ("Dock", "low", KIND_REFERENCE),
        ("Ship", "high", KIND_REFERENCE),
        ("Yard", "high", KIND_REFERENCE),
    ]
    assert _labels(_complete(registry, f'{HEADER}targetEntity "sh|', chain=chain)) == ["Ship"]


def test_reference_completion_is_limited_to_usable_layers_on_an_incomplete_chain(
    registry: Registry, tmp_path: Path
) -> None:
    chain = _chain_index(tmp_path, complete=False)

    items = _complete(registry, f'{HEADER}targetEntity "|', chain=chain)

    assert _labels(items) == ["Dock", "Ship", "Yard"]
    assert "gone" not in {i.detail for i in items}


def test_reference_completion_is_empty_without_a_chain(registry: Registry) -> None:
    assert _complete(registry, f'{HEADER}targetEntity "|') == []


def _hover(registry: Registry, marked: str, chain: ChainIndex | None = None):
    text, position = _cursor(marked)
    return hover(text, position, AssistContext(registry, REBELLION, FILE, chain))


def test_hover_over_a_key_gives_help_type_required_status_and_gate(registry: Registry) -> None:
    result = _hover(registry, f'{HEADER}hull|Type "Light"\n')

    assert result is not None
    assert "Hull class." in result.contents
    assert "Type: HullKind" in result.contents
    assert "Required: yes" in result.contents
    assert result.range is not None
    gated = _hover(registry, f"{HEADER}sh|ield 1.000000\n")
    assert gated is not None
    assert "Version: Rebellion" in gated.contents
    assert "Required: no" in gated.contents


def test_hover_over_a_key_with_no_definition_returns_nothing(registry: Registry) -> None:
    assert _hover(registry, f"{HEADER}mystery| 5\n") is None
    assert _hover(registry, f"{HEADER}|\n") is None
    assert _hover(registry, f'{HEADER}hullType "Light"\n\tstr|ay 1\n') is None


def test_hover_over_an_enum_value_gives_the_member_help(registry: Registry) -> None:
    result = _hover(registry, f'{HEADER}hullType "Li|ght"\n')

    assert result is not None
    assert result.contents == "A small hull."
    assert _hover(registry, f'{HEADER}hullType "Pl|ain"\n') is None


def test_hover_over_a_reference_names_the_layer_and_the_one_it_overrides(
    registry: Registry, tmp_path: Path
) -> None:
    chain = _chain_index(tmp_path)

    overridden = _hover(registry, f'{HEADER}targetEntity "Sh|ip"\n', chain)
    single = _hover(registry, f'{HEADER}targetEntity "Do|ck"\n', chain)

    assert overridden is not None
    assert "provided by Layer `high`" in overridden.contents
    assert "overrides the same name in Layer `low`" in overridden.contents
    assert single is not None
    assert "provided by Layer `low`" in single.contents
    assert "overrides" not in single.contents
    assert _hover(registry, f'{HEADER}targetEntity "Mi|ssing"\n', chain) is None


def test_hover_matches_references_ignoring_case(registry: Registry, tmp_path: Path) -> None:
    chain = _chain_index(tmp_path)

    result = _hover(registry, f'{HEADER}targetEntity "sh|IP"\n', chain)

    assert result is not None
    assert "provided by Layer `high`" in result.contents


def test_go_to_definition_opens_the_highest_layers_file(registry: Registry, tmp_path: Path) -> None:
    chain = _chain_index(tmp_path)

    text, position = _cursor(f'{HEADER}targetEntity "Sh|ip"\n')
    ship = goto_definition(text, position, AssistContext(registry, REBELLION, FILE, chain))
    text, position = _cursor(f'{HEADER}targetEntity "Do|ck"\n')
    dock = goto_definition(text, position, AssistContext(registry, REBELLION, FILE, chain))

    assert ship is not None
    assert ship.file == tmp_path / "high" / "GameInfo" / "Ship.entity"
    assert dock is not None
    assert dock.file == tmp_path / "low" / "GameInfo" / "Dock.entity"


def test_go_to_definition_returns_nothing_off_a_resolvable_reference(
    registry: Registry, tmp_path: Path
) -> None:
    chain = _chain_index(tmp_path)

    for marked in (
        f'{HEADER}targetEntity "Mi|ssing"\n',
        f'{HEADER}target|Entity "Ship"\n',
        f'{HEADER}hullType "Li|ght"\n',
    ):
        text, position = _cursor(marked)
        assert (
            goto_definition(text, position, AssistContext(registry, REBELLION, FILE, chain)) is None
        )
    text, position = _cursor(f'{HEADER}targetEntity "Sh|ip"\n')
    assert goto_definition(text, position, AssistContext(registry, REBELLION, FILE)) is None


def test_field_help_describes_a_field_and_prefers_the_version_that_defines_it(
    registry: Registry,
) -> None:
    info = field_help(registry, "Frigate", "hullType", REBELLION)

    assert info is not None
    assert (info.structure, info.field, info.validation_type) == ("Frigate", "hullType", "HullKind")
    assert info.required
    assert info.help == "Hull class."
    gated = field_help(registry, "Frigate", "shield", REBELLION)
    assert gated is not None
    assert gated.version_gate == "Rebellion"
    branch = field_help(registry, "Frigate", "soloOnly", REBELLION)
    assert branch is not None
    assert branch.validation_type == "Integer"
    assert field_help(registry, "Frigate", "nope", REBELLION) is None
    assert field_help(registry, "Nope", "hullType", REBELLION) is None
