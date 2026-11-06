"""Unit tests for engine.model and engine.diagnostics."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sose_validator.engine import diagnostics as dg
from sose_validator.engine.model import Diagnostic, Position, Range, Severity, Span


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
        "SOSE-P001", "SOSE-P002", "SOSE-P003", "SOSE-P004",
        "SOSE-V010", "SOSE-V020", "SOSE-V030", "SOSE-V040",
        "SOSE-R010", "SOSE-C010", "SOSE-C020", "SOSE-C030",
        "SOSE-M010", "SOSE-M020", "SOSE-M030", "SOSE-M040",
        "SOSE-D001", "SOSE-X001",
    }  # fmt: skip
    assert set(dg.CODE_CATALOGUE) == expected
    assert all(i.code[5] == i.family for i in dg.CODE_CATALOGUE.values())


def test_filter_disabled_removes_only_disabled_codes() -> None:
    items = [_diag(dg.V020), _diag(dg.C030), _diag(dg.V020)]
    assert dg.filter_disabled(items, {dg.C030}) == [items[0], items[2]]
    assert dg.filter_disabled(items, []) == items
