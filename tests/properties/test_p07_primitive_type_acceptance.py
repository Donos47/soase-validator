"""Property test for primitive type acceptance.

# Feature: soase-validator, Property 7: Primitive type acceptance

Each primitive checker accepts exactly the shapes in design.md ("Validator" >
"Primitive rules and evidence") and rejects near-miss shapes:

* Boolean: ``TRUE`` and ``FALSE`` only.
* Integer and Decimal: plain, negative and leading-point forms; exponent,
  leading ``+`` and trailing point rejected; ``integer_strict`` and
  ``decimal_allow_integer`` keep their meaning.
* Color: 8, 6 or 4 hex digits in any case, or a lone ``0``; no ``0x``, no
  quotes, no other length.
* Position: bracketed comma separated integers, item count from
  ``count=N``; a malformed ``constraint`` raises ``ValueError`` and is
  reported by ``validate_constraint``.
* Coordinate: exactly 3 whitespace separated numbers.
* Orientation: value-less header with exactly 3 keyless Coordinate rows.

**Validates: Requirements 3.3, 3.3.1, 3.3.2, 3.3.3, 3.3.4, 3.3.5, 3.3.6**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.primitives import (
    bad_color_texts,
    bad_number_texts,
    color_texts,
    color_value,
    coordinate_item_texts,
    coordinate_value,
    decimal_texts,
    integer_texts,
    keyless_row,
    malformed_constraints,
    non_boolean_values,
    non_number_values,
    number_texts,
    number_value,
    orientation_header,
    position_counts,
    position_value,
    quoted_color_values,
    unconstrained_types,
)

from soase_validator.engine.parser import BoolValue, ListValue, StringValue
from soase_validator.engine.primitives import (
    NumericPrefs,
    check_boolean,
    check_color,
    check_coordinate,
    check_decimal,
    check_integer,
    check_orientation,
    check_position,
    validate_constraint,
)

prefs_strategy = st.builds(NumericPrefs, st.booleans(), st.booleans())

_SETTINGS = settings(max_examples=100)


def _rejected(result) -> bool:
    """Return True for a failing result that carries a message."""
    return (not result.ok) and bool(result.message)


@_SETTINGS
@given(flag=st.booleans(), prefs=prefs_strategy)
def test_boolean_accepts_true_and_false(flag: bool, prefs: NumericPrefs) -> None:
    assert check_boolean(BoolValue(flag), prefs).ok


@_SETTINGS
@given(raw=non_boolean_values, prefs=prefs_strategy)
def test_boolean_rejects_everything_else(raw, prefs: NumericPrefs) -> None:
    assert _rejected(check_boolean(raw, prefs))


@_SETTINGS
@given(text=integer_texts, prefs=prefs_strategy)
def test_integer_accepts_integer_form(text: str, prefs: NumericPrefs) -> None:
    assert check_integer(number_value(text), prefs).ok


@_SETTINGS
@given(text=decimal_texts, prefs=prefs_strategy)
def test_integer_decimal_form_depends_on_strict(text: str, prefs: NumericPrefs) -> None:
    result = check_integer(number_value(text), prefs)
    assert result.ok is (not prefs.integer_strict)


@_SETTINGS
@given(text=bad_number_texts, prefs=prefs_strategy)
def test_integer_rejects_bad_number_forms(text: str, prefs: NumericPrefs) -> None:
    assert _rejected(check_integer(number_value(text), prefs))


@_SETTINGS
@given(text=decimal_texts, prefs=prefs_strategy)
def test_decimal_accepts_decimal_form(text: str, prefs: NumericPrefs) -> None:
    assert check_decimal(number_value(text), prefs).ok


@_SETTINGS
@given(text=integer_texts, prefs=prefs_strategy)
def test_decimal_integer_form_depends_on_pref(text: str, prefs: NumericPrefs) -> None:
    result = check_decimal(number_value(text), prefs)
    assert result.ok is prefs.decimal_allow_integer


@_SETTINGS
@given(text=bad_number_texts, prefs=prefs_strategy)
def test_decimal_rejects_bad_number_forms(text: str, prefs: NumericPrefs) -> None:
    assert _rejected(check_decimal(number_value(text), prefs))


@_SETTINGS
@given(raw=non_number_values, prefs=prefs_strategy)
def test_integer_and_decimal_reject_non_numbers(raw, prefs: NumericPrefs) -> None:
    assert _rejected(check_integer(raw, prefs))
    assert _rejected(check_decimal(raw, prefs))


@_SETTINGS
@given(text=color_texts, prefs=prefs_strategy)
def test_color_accepts_8_6_4_hex_digits_or_zero(text: str, prefs: NumericPrefs) -> None:
    assert check_color(color_value(text), prefs).ok


@_SETTINGS
@given(text=bad_color_texts, prefs=prefs_strategy)
def test_color_rejects_near_misses(text: str, prefs: NumericPrefs) -> None:
    assert _rejected(check_color(color_value(text), prefs))


@_SETTINGS
@given(raw=quoted_color_values, prefs=prefs_strategy)
def test_color_rejects_quoted_values(raw, prefs: NumericPrefs) -> None:
    assert _rejected(check_color(raw, prefs))


@_SETTINGS
@given(
    raw=st.one_of(
        st.builds(BoolValue, st.booleans()),
        st.builds(position_value, st.lists(integer_texts, min_size=1, max_size=4)),
    ),
    prefs=prefs_strategy,
)
def test_color_rejects_non_token_values(raw, prefs: NumericPrefs) -> None:
    assert _rejected(check_color(raw, prefs))


@_SETTINGS
@given(data=st.data(), count=position_counts)
def test_position_accepts_matching_count(data, count: int) -> None:
    items = data.draw(st.lists(integer_texts, min_size=count, max_size=count))
    assert check_position(position_value(items), NumericPrefs(), f"count={count}").ok


@_SETTINGS
@given(items=st.lists(integer_texts, min_size=1, max_size=8))
def test_position_without_constraint_checks_shape_only(items: list[str]) -> None:
    assert check_position(position_value(items), NumericPrefs()).ok


@_SETTINGS
@given(data=st.data(), count=position_counts, other=position_counts)
def test_position_rejects_wrong_count(data, count: int, other: int) -> None:
    if other == count:
        other = count + 1
    items = data.draw(st.lists(integer_texts, min_size=other, max_size=other))
    assert _rejected(check_position(position_value(items), NumericPrefs(), f"count={count}"))


@_SETTINGS
@given(
    data=st.data(),
    count=position_counts,
    bad=st.one_of(
        st.builds(lambda i, f: f"{i}.{f}", integer_texts, st.just("5")), number_texts
    ).filter(lambda t: "." in t or "e" in t.lower()),
)
def test_position_rejects_decimal_items(data, count: int, bad: str) -> None:
    items = data.draw(st.lists(integer_texts, min_size=count, max_size=count))
    items[data.draw(st.integers(0, count - 1))] = bad
    assert _rejected(check_position(position_value(items), NumericPrefs(), f"count={count}"))


@_SETTINGS
@given(items=st.lists(integer_texts, min_size=2, max_size=6))
def test_position_rejects_space_separated_list(items: list[str]) -> None:
    result = check_position(position_value(items, " "), NumericPrefs(), f"count={len(items)}")
    assert _rejected(result)


@_SETTINGS
@given(raw=non_number_values.filter(lambda v: not isinstance(v, ListValue)), count=position_counts)
def test_position_rejects_non_lists(raw, count: int) -> None:
    assert _rejected(check_position(raw, NumericPrefs(), f"count={count}"))
    assert _rejected(check_position(number_value("1"), NumericPrefs(), f"count={count}"))


@_SETTINGS
@given(count=position_counts)
def test_validate_constraint_accepts_count_n(count: int) -> None:
    assert validate_constraint("Position", f"count={count}") is None
    assert validate_constraint("Position", None) is None


@_SETTINGS
@given(constraint=malformed_constraints)
def test_malformed_constraint_reported_and_raises(constraint: str) -> None:
    assert validate_constraint("Position", constraint)
    with pytest.raises(ValueError):
        check_position(position_value(["1", "2"]), NumericPrefs(), constraint)


@_SETTINGS
@given(validation=unconstrained_types, count=position_counts)
def test_validate_constraint_rejects_constraint_on_other_types(validation: str, count: int) -> None:
    assert validate_constraint(validation, f"count={count}")
    assert validate_constraint(validation, None) is None


@_SETTINGS
@given(items=coordinate_item_texts, prefs=prefs_strategy)
def test_coordinate_accepts_three_space_separated_numbers(
    items: list[str], prefs: NumericPrefs
) -> None:
    assert check_coordinate(coordinate_value(items), prefs).ok


@_SETTINGS
@given(
    items=st.lists(number_texts, min_size=0, max_size=7).filter(lambda x: len(x) != 3),
    prefs=prefs_strategy,
)
def test_coordinate_rejects_wrong_item_count(items: list[str], prefs: NumericPrefs) -> None:
    assert _rejected(check_coordinate(coordinate_value(items), prefs))


@_SETTINGS
@given(items=coordinate_item_texts, prefs=prefs_strategy)
def test_coordinate_rejects_comma_separated_list(items: list[str], prefs: NumericPrefs) -> None:
    assert _rejected(check_coordinate(coordinate_value(items, ","), prefs))


@_SETTINGS
@given(items=coordinate_item_texts, bad=bad_number_texts, index=st.integers(0, 2))
def test_coordinate_rejects_bad_number_items(items: list[str], bad: str, index: int) -> None:
    items[index] = bad
    assert _rejected(check_coordinate(coordinate_value(items), NumericPrefs()))


@_SETTINGS
@given(raw=non_number_values.filter(lambda v: not isinstance(v, ListValue)))
def test_coordinate_rejects_non_lists(raw) -> None:
    assert _rejected(check_coordinate(raw, NumericPrefs()))


def _rows(item_sets: list[list[str]]):
    return [keyless_row(coordinate_value(items)) for items in item_sets]


@_SETTINGS
@given(item_sets=st.lists(coordinate_item_texts, min_size=3, max_size=3), prefs=prefs_strategy)
def test_orientation_accepts_three_keyless_coordinate_rows(
    item_sets: list[list[str]], prefs: NumericPrefs
) -> None:
    assert check_orientation(orientation_header(_rows(item_sets)), prefs).ok


@_SETTINGS
@given(
    item_sets=st.lists(coordinate_item_texts, max_size=6).filter(lambda x: len(x) != 3),
)
def test_orientation_rejects_wrong_row_count(item_sets: list[list[str]]) -> None:
    assert _rejected(check_orientation(orientation_header(_rows(item_sets)), NumericPrefs()))


@_SETTINGS
@given(
    item_sets=st.lists(coordinate_item_texts, min_size=3, max_size=3),
    value=st.one_of(
        st.just(BoolValue(True)), st.just(StringValue("x")), st.just(number_value("1"))
    ),
)
def test_orientation_rejects_header_with_value(item_sets, value) -> None:
    header = orientation_header(_rows(item_sets), value)
    assert _rejected(check_orientation(header, NumericPrefs()))


@_SETTINGS
@given(
    item_sets=st.lists(coordinate_item_texts, min_size=3, max_size=3),
    index=st.integers(0, 2),
    key=st.text(alphabet="abcxyz", min_size=1, max_size=5),
)
def test_orientation_rejects_keyed_row(item_sets, index: int, key: str) -> None:
    rows = _rows(item_sets)
    rows[index] = keyless_row(coordinate_value(item_sets[index]), key)
    assert _rejected(check_orientation(orientation_header(rows), NumericPrefs()))


@_SETTINGS
@given(
    item_sets=st.lists(coordinate_item_texts, min_size=3, max_size=3),
    index=st.integers(0, 2),
    bad=bad_number_texts,
    wrong_count=st.booleans(),
)
def test_orientation_rejects_bad_coordinate_row(
    item_sets, index: int, bad: str, wrong_count: bool
) -> None:
    rows = _rows(item_sets)
    items = list(item_sets[index])
    if wrong_count:
        items = items[:2]
    else:
        items[0] = bad
    rows[index] = keyless_row(coordinate_value(items))
    assert _rejected(check_orientation(orientation_header(rows), NumericPrefs()))


@_SETTINGS
@given(item_sets=st.lists(coordinate_item_texts, min_size=3, max_size=3), index=st.integers(0, 2))
def test_orientation_rejects_valueless_or_nested_row(item_sets, index: int) -> None:
    rows = _rows(item_sets)
    rows[index] = keyless_row(None)
    assert _rejected(check_orientation(orientation_header(rows), NumericPrefs()))
    rows = _rows(item_sets)
    rows[index].children.append(keyless_row(coordinate_value(item_sets[index])))
    assert _rejected(check_orientation(orientation_header(rows), NumericPrefs()))
