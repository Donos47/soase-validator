"""Property test for numeric strictness.

# Feature: soase-validator, Property 8: Numeric strictness

Number form rules (design.md, "Primitive rules and evidence", items 4 and 5)
for Integer, Decimal and Coordinate items:

* Exponents, a leading ``+`` and a trailing ``.`` are rejected for every
  combination of ``integer_strict`` and ``decimal_allow_integer``.
* Leading-point forms (``.5``, ``-.5``) and negatives are accepted.
* ``integer_strict`` rejects an Integer written with a decimal point.
* ``decimal_allow_integer`` decides whether a Decimal may be written in
  integer form.

**Validates: Requirements 3.10, 3.3.5**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.primitives import (
    coordinate_item_texts,
    coordinate_value,
    decimal_texts,
    integer_texts,
    leading_dot_texts,
    number_texts,
    number_value,
)

from soase_validator.engine.primitives import (
    NumericPrefs,
    check_coordinate,
    check_decimal,
    check_integer,
)

prefs_strategy = st.builds(NumericPrefs, st.booleans(), st.booleans())

_SETTINGS = settings(max_examples=100)

_unsigned = st.text(alphabet="0123456789", min_size=1, max_size=8)

#: A good number followed by an exponent part, for example ``1.5e-3``.
exponent_texts = st.builds(
    lambda t, e, s, d: f"{t}{e}{s}{d}",
    number_texts,
    st.sampled_from(["e", "E"]),
    st.sampled_from(["", "+", "-"]),
    _unsigned,
)

#: A good number with a leading ``+``, for example ``+3`` or ``+-1.5``.
plus_texts = st.builds(lambda t: "+" + t, number_texts)

#: An integer form with a trailing point, for example ``5.`` or ``-12.``.
trailing_dot_texts = st.builds(lambda t: t + ".", integer_texts)

#: Any of the three rejected forms.
rejected_form_texts = st.one_of(exponent_texts, plus_texts, trailing_dot_texts)

#: Negative forms: integer, pointed decimal and leading-point decimal.
negative_texts = st.builds(
    lambda t: t if t.startswith("-") else "-" + t,
    st.one_of(integer_texts, decimal_texts),
)


@_SETTINGS
@given(text=rejected_form_texts, prefs=prefs_strategy)
def test_integer_and_decimal_reject_exponent_plus_trailing_dot(
    text: str, prefs: NumericPrefs
) -> None:
    assert not check_integer(number_value(text), prefs).ok
    assert not check_decimal(number_value(text), prefs).ok


@_SETTINGS
@given(
    text=rejected_form_texts,
    index=st.integers(0, 2),
    items=coordinate_item_texts,
    prefs=prefs_strategy,
)
def test_coordinate_items_reject_exponent_plus_trailing_dot(
    text: str, index: int, items: list[str], prefs: NumericPrefs
) -> None:
    items[index] = text
    assert not check_coordinate(coordinate_value(items), prefs).ok


@_SETTINGS
@given(text=leading_dot_texts, prefs=prefs_strategy)
def test_leading_dot_forms_accepted_as_decimal(text: str, prefs: NumericPrefs) -> None:
    assert check_decimal(number_value(text), prefs).ok


@_SETTINGS
@given(text=leading_dot_texts)
def test_leading_dot_integer_follows_integer_strict(text: str) -> None:
    assert check_integer(number_value(text), NumericPrefs(integer_strict=False)).ok
    assert not check_integer(number_value(text), NumericPrefs(integer_strict=True)).ok


@_SETTINGS
@given(text=negative_texts, prefs=prefs_strategy)
def test_negatives_accepted(text: str, prefs: NumericPrefs) -> None:
    is_integer_form = "." not in text
    integer_ok = check_integer(number_value(text), prefs).ok
    decimal_ok = check_decimal(number_value(text), prefs).ok
    assert integer_ok is (is_integer_form or not prefs.integer_strict)
    assert decimal_ok is (not is_integer_form or prefs.decimal_allow_integer)


@_SETTINGS
@given(
    items=st.lists(st.one_of(leading_dot_texts, negative_texts), min_size=3, max_size=3),
    prefs=prefs_strategy,
)
def test_coordinate_accepts_leading_dot_and_negative_items(
    items: list[str], prefs: NumericPrefs
) -> None:
    assert check_coordinate(coordinate_value(items), prefs).ok


@_SETTINGS
@given(text=decimal_texts, allow=st.booleans())
def test_integer_strict_rejects_decimal_point_for_integer(text: str, allow: bool) -> None:
    strict = NumericPrefs(integer_strict=True, decimal_allow_integer=allow)
    relaxed = NumericPrefs(integer_strict=False, decimal_allow_integer=allow)
    assert not check_integer(number_value(text), strict).ok
    assert check_integer(number_value(text), relaxed).ok


@_SETTINGS
@given(text=integer_texts, strict=st.booleans())
def test_decimal_allow_integer_controls_integer_form_decimals(text: str, strict: bool) -> None:
    allowed = NumericPrefs(integer_strict=strict, decimal_allow_integer=True)
    denied = NumericPrefs(integer_strict=strict, decimal_allow_integer=False)
    assert check_decimal(number_value(text), allowed).ok
    assert not check_decimal(number_value(text), denied).ok
    assert check_integer(number_value(text), denied).ok
