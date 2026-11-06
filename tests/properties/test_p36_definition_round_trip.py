"""Property test for the Definition load round trip."""

# Feature: soase-validator, Property 36: Definition load round trip

from __future__ import annotations

from hypothesis import given, settings
from tests.strategies.definitions import (
    DefinitionSet,
    definitions,
    load,
    registry_differences,
)

from soase_validator.engine.registry import Registry


def _content(registry: Registry) -> DefinitionSet:
    """Rebuild a DefinitionSet from the content of a loaded Registry.

    Args:
        registry: A loaded Registry.

    Returns:
        A DefinitionSet holding the Registry's structures, element rules and enums.

    Raises:
        AssertionError: If a name listed by the Registry cannot be looked up.
    """
    structures = []
    for name in registry.structure_names:
        struct = registry.structure(name)
        assert struct is not None
        structures.append(struct)
    enums = []
    for name in registry.enum_names:
        enum = registry.enum(name)
        assert enum is not None
        enums.append(enum)
    # Element rules have no name listing; the original model supplies the names.
    return DefinitionSet(tuple(structures), (), tuple(enums))


# **Validates: Requirements 1.2**
@settings(max_examples=100)
@given(defs=definitions())
def test_serialize_and_load_equals_model(defs: DefinitionSet) -> None:
    """Loading serialized Definitions gives zero warnings and an equal model."""
    registry = load(defs)
    assert registry.warnings == ()
    assert registry_differences(defs, registry) == []


# **Validates: Requirements 1.2**
@settings(max_examples=100)
@given(defs=definitions())
def test_reserialize_loaded_registry_is_stable(defs: DefinitionSet) -> None:
    """Re-serializing a loaded Registry and reloading gives an equal Registry."""
    registry = load(defs)
    rules = tuple(
        rule for r in defs.element_rules if (rule := registry.element_rule(r.name)) is not None
    )
    rebuilt = DefinitionSet(_content(registry).structures, rules, _content(registry).enums)
    second = load(rebuilt)
    assert registry_differences(rebuilt, second) == []
    assert registry_differences(defs, second) == []
