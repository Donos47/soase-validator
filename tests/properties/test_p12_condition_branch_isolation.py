"""Property test for condition branch isolation.

# Feature: soase-validator, Property 12: Condition branch isolation

For any condition field, selector value and generated file, validation accepts
exactly the keys of the selected branch, and keys that exist only in other
branches are reported as undefined (Requirement 3.8). The undefined key is
``SOASE-V020`` on the key.

Synthetic Definitions only; no game files.

**Validates: Requirements 3.8**
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.definitions import enum_to_json

from soase_validator.engine.diagnostics import V020
from soase_validator.engine.parser import parse
from soase_validator.engine.registry import EnumDef, EnumValueDef, load_registry_from_texts
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import GameVersion

_SELECTOR = "kind"


@st.composite
def _branch_sets(draw: st.DrawFn) -> dict[str, list[str]]:
    """Draw branches: selector value -> key names unique across all branches."""
    count = draw(st.integers(min_value=2, max_value=4))
    sizes = draw(st.lists(st.integers(min_value=0, max_value=3), min_size=count, max_size=count))
    return {f"V{i}": [f"b{i}k{j}" for j in range(size)] for i, size in enumerate(sizes)}


def _registry(branches: dict[str, list[str]]):
    """Load a root structure whose ``kind`` condition field has the given branches."""
    enum = EnumDef(name="Sel", values=tuple(EnumValueDef(v, None) for v in branches), version=None)
    selector = {
        "node": "condition_field",
        "name": _SELECTOR,
        "type": "Sel",
        "branches": {
            value: [{"node": "field", "name": key, "validation": "Integer"} for key in keys]
            for value, keys in branches.items()
        },
    }
    root = {"name": "Root", "extension": ".foo", "children": [selector]}
    registry = load_registry_from_texts(
        {
            "s.json": json.dumps({"structures": [root]}),
            "enums.json": json.dumps({"enums": [enum_to_json(enum)]}),
        }
    )
    assert registry.warnings == ()
    return registry


def _validate(branches: dict[str, list[str]], lines: list[str]):
    """Validate a ``TXT`` file made of ``lines`` against the branches."""
    path = Path("a.foo")
    text = "TXT\n" + "\n".join(lines) + "\n"
    context = ValidationContext(_registry(branches), GameVersion.REBELLION_198, path)
    return validate(parse(text, path), context)


def _file(selected: str, branches: dict[str, list[str]]) -> list[str]:
    """Lines of a file selecting ``selected`` and giving every key of its branch."""
    return [f'{_SELECTOR} "{selected}"', *(f"{key} 1" for key in branches[selected])]


@settings(max_examples=100)
@given(branches=_branch_sets(), data=st.data())
def test_selected_branch_keys_are_accepted(branches: dict[str, list[str]], data) -> None:
    """The keys of the selected branch validate cleanly."""
    selected = data.draw(st.sampled_from(list(branches)))
    assert _validate(branches, _file(selected, branches)) == []


@settings(max_examples=100)
@given(branches=_branch_sets(), data=st.data())
def test_keys_only_in_other_branches_are_undefined(branches: dict[str, list[str]], data) -> None:
    """A key that only another branch defines is ``SOASE-V020`` on that key."""
    selected = data.draw(st.sampled_from(list(branches)))
    foreign = [(v, k) for v, keys in branches.items() if v != selected for k in keys]
    if not foreign:
        return
    _, key = data.draw(st.sampled_from(foreign))
    lines = [*_file(selected, branches), f"{key} 1"]
    diags = _validate(branches, lines)
    assert [d.code for d in diags] == [V020]
    (diag,) = diags
    assert diag.range.start.line == len(lines)
    assert diag.range.start.col == 0
    assert diag.range.end.col == len(key)


@settings(max_examples=100)
@given(branches=_branch_sets(), data=st.data())
def test_selector_value_decides_which_keys_are_defined(
    branches: dict[str, list[str]], data
) -> None:
    """The same key line is accepted under its own selector and rejected under another."""
    owners = [(v, k) for v, keys in branches.items() for k in keys]
    if not owners:
        return
    owner, key = data.draw(st.sampled_from(owners))
    other = data.draw(st.sampled_from([v for v in branches if v != owner]))
    assert _validate(branches, _file(owner, branches)) == []
    lines = [*_file(other, branches), f"{key} 1"]
    assert [d.code for d in _validate(branches, lines)] == [V020]
