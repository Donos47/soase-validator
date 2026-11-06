"""Sanity checks for the Definitions strategy and serializer."""

from __future__ import annotations

from hypothesis import given, settings
from tests.strategies.definitions import (
    DefinitionSet,
    definitions,
    load,
    registry_differences,
)


@settings(max_examples=100)
@given(defs=definitions())
def test_generated_definitions_load_cleanly(defs: DefinitionSet) -> None:
    """Generated Definitions load with no warnings and match the model."""
    assert registry_differences(defs, load(defs)) == []


@settings(max_examples=100)
@given(defs=definitions())
def test_split_across_files_is_equivalent(defs: DefinitionSet) -> None:
    """The number of structure files does not change the loaded result."""
    assert registry_differences(defs, load(defs, structure_files=1)) == []
