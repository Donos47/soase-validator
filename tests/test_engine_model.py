"""Unit tests for engine.model and engine.diagnostics."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.model import Diagnostic, Position, Range, Severity, Span


def _diag(code: str) -> Diagnostic:
    """Build a Diagnostic with the given code."""
    rng = Range(Position(0, 0), Position(0, 1))
    return Diagnostic(Path("a.entity"), rng, Severity.ERROR, code, "msg")


def test_models_are_frozen_and_slotted() -> None:
    pos = Position(1, 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pos.line = 3  # type: ignore[misc]
    assert not hasattr(pos, "__dict__")


def test_span_to_range_is_zero_based() -> None:
    assert Span(0, 1, 2, 3).to_range() == Range(Position(0, 1), Position(2, 3))


def test_catalogue_contains_required_codes() -> None:
    expected = {
        "SOASE-P001", "SOASE-P002", "SOASE-P003", "SOASE-P004",
        "SOASE-V010", "SOASE-V020", "SOASE-V030", "SOASE-V040",
        "SOASE-V050", "SOASE-V060", "SOASE-V070", "SOASE-V080",
        "SOASE-R010",
        "SOASE-C010", "SOASE-C020", "SOASE-C030", "SOASE-C040",
        "SOASE-M010", "SOASE-M020", "SOASE-M030", "SOASE-M040",
        "SOASE-D001", "SOASE-X001",
    }  # fmt: skip
    assert set(dg.CODE_CATALOGUE) == expected
    assert all(i.code.removeprefix("SOASE-")[0] == i.family for i in dg.CODE_CATALOGUE.values())


def test_filter_disabled_removes_only_disabled_codes() -> None:
    items = [_diag(dg.V020), _diag(dg.C030), _diag(dg.V020)]
    assert dg.filter_disabled(items, {dg.C030}) == [items[0], items[2]]
    assert dg.filter_disabled(items, []) == items
