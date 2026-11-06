"""Property test for disabled Diagnostic code filtering."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from sose_validator.engine.diagnostics import CODE_CATALOGUE, filter_disabled
from sose_validator.engine.model import Diagnostic, Position, Range, Severity

_CODES = sorted(CODE_CATALOGUE)

_positions = st.builds(
    Position,
    line=st.integers(min_value=0, max_value=1000),
    col=st.integers(min_value=0, max_value=200),
)

_diagnostics = st.builds(
    Diagnostic,
    file=st.just(Path("a.entity")),
    range=st.builds(Range, start=_positions, end=_positions),
    severity=st.sampled_from(list(Severity)),
    code=st.sampled_from(_CODES),
    message=st.text(max_size=20),
)


def _mixed_case(code: str, flips: list[bool]) -> str:
    """Return ``code`` with letter case flipped where ``flips`` is true.

    Args:
        code: Original code string.
        flips: Per-character flip flags; shorter lists are padded with False.

    Returns:
        The code with selected characters case-swapped.

    Raises:
        None.
    """
    return "".join(c.swapcase() if i < len(flips) and flips[i] else c for i, c in enumerate(code))


# Feature: sose-validator, Property 23: Disabled codes are filtered
# **Validates: Requirements 8.5**
@settings(max_examples=100)
@given(
    diagnostics=st.lists(_diagnostics, max_size=30),
    disabled=st.lists(st.sampled_from(_CODES), max_size=6),
    flips=st.lists(st.booleans(), max_size=12),
)
def test_disabled_codes_are_filtered(
    diagnostics: list[Diagnostic],
    disabled: list[str],
    flips: list[bool],
) -> None:
    """Result drops disabled codes and keeps all others in original order."""
    disabled_variants = [_mixed_case(c, flips) for c in disabled]
    disabled_set = {c.upper() for c in disabled_variants}

    result = filter_disabled(diagnostics, disabled_variants)

    assert all(d.code.upper() not in disabled_set for d in result)
    assert result == [d for d in diagnostics if d.code.upper() not in disabled_set]
