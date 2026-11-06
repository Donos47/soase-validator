"""Property test for gate monotonicity on Rebellion 1.98.

# Feature: soase-validator, Property 10: Gate monotonicity for Rebellion 1.98

**Validates: Requirements 3.9, 13.8**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from soase_validator.engine.versions import (
    GATE_TOKENS,
    GameVersion,
    VersionData,
    gate_allows,
)

_NO_OVERRIDES = VersionData()
_TOKENS = sorted(GATE_TOKENS) + ["Unknown", "Rebellion198"]
_token_lists = st.lists(st.sampled_from(_TOKENS), max_size=6)
_separators = st.sampled_from([",", " ", ", "])


@st.composite
def _gates(draw: st.DrawFn) -> str:
    """Build a gate expression from tokens and mixed separators."""
    tokens = draw(_token_lists)
    sep = draw(_separators)
    return sep.join(tokens)


@settings(max_examples=100)
@given(gate=_gates())
def test_198_equals_194_without_overrides(gate: str) -> None:
    """With no overrides, 1.98 allows exactly what 194 allows."""
    r198 = gate_allows(gate, GameVersion.REBELLION_198, _NO_OVERRIDES)
    r194 = gate_allows(gate, GameVersion.REBELLION_194, _NO_OVERRIDES)
    assert r198 == r194
    if r194:
        assert r198


@settings(max_examples=100)
@given(base=st.lists(st.sampled_from(_TOKENS), min_size=1, max_size=6), extra=_token_lists)
def test_adding_tokens_never_disallows(base: list[str], extra: list[str]) -> None:
    """Union of tokens into a non-empty allowed gate keeps it allowed at 1.98.

    An empty gate allows everything by definition, so it is not a base here.
    """
    gate = ", ".join(base)
    union = ", ".join([*base, *extra])
    if gate_allows(gate, GameVersion.REBELLION_198, _NO_OVERRIDES):
        assert gate_allows(union, GameVersion.REBELLION_198, _NO_OVERRIDES)
