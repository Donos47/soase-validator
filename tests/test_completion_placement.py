"""Completion, hover and go-to-definition locate blocks from the placed tree.

A line belongs to the block its key names, whatever its indentation. The
assistance functions use the same placement as validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine.completion import AssistContext, complete, hover
from soase_validator.engine.model import Position
from soase_validator.engine.registry import Registry, load_registry_from_texts
from soase_validator.engine.versions import GameVersion

FILE = Path("GameInfo/Ship.entity")
HEADER = 'TXT2\nSinsArchiveVersion 194\nentityType "Frigate"\n'

_STRUCTURES = {
    "structures": [
        {
            "name": "Frigate",
            "children": [
                {"node": "structure_reference", "name": "outer", "structure": "Outer"},
            ],
        },
        {
            "name": "Outer",
            "children": [
                {"node": "structure_reference", "name": "inner", "structure": "Inner"},
                {"node": "field", "name": "z", "validation": "Integer"},
            ],
        },
        {
            "name": "Inner",
            "children": [
                {"node": "field", "name": "x", "validation": "Integer"},
                {"node": "field", "name": "y", "type": "Kind", "help": "The y field."},
            ],
        },
    ]
}
_ENUMS = {
    "enums": [
        {"name": "entityType", "values": ["Frigate"]},
        {"name": "Kind", "values": ["Alpha", "Beta"]},
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


def _split(marked: str) -> tuple[str, Position]:
    """Split a document at the ``|`` marker into text and cursor position."""
    before, after = marked.split("|")
    lines = before.split("\n")
    return before + after, Position(len(lines) - 1, len(lines[-1]))


def _complete(registry: Registry, marked: str) -> list[str]:
    text, position = _split(marked)
    ctx = AssistContext(registry, GameVersion.REBELLION_198, FILE)
    return [item.label for item in complete(text, position, ctx)]


def test_cursor_after_an_over_indented_header_is_inside_that_block(registry: Registry) -> None:
    assert _complete(registry, f"{HEADER}outer\n        inner\n            |") == ["x", "y"]


def test_value_completion_finds_the_field_of_a_shallow_member(registry: Registry) -> None:
    marked = f"{HEADER}outer\n    inner\n    x 1\n    y |"

    assert _complete(registry, marked) == ["Alpha", "Beta"]


def test_hover_resolves_a_shallow_member_to_the_block_validation_uses(registry: Registry) -> None:
    text, position = _split(f'{HEADER}outer\n    inner\n    x 1\n    |y "Alpha"')
    ctx = AssistContext(registry, GameVersion.REBELLION_198, FILE)

    result = hover(text, position, ctx)

    assert result is not None
    assert "The y field." in result.contents


def test_key_completion_on_a_normally_indented_block_is_unchanged(registry: Registry) -> None:
    assert _complete(registry, f"{HEADER}outer\n    inner\n        x 1\n        |") == ["y"]
