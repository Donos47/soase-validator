"""Example tests for the primitive checkers.

Shapes are real-shaped synthetic values: TRUE/FALSE only, plain and negative
integers, six-place and leading-point decimals, integer fields written as
decimals and decimal fields written as integers.
"""

from __future__ import annotations

import pytest

from soase_validator.engine.parser import Node, parse
from soase_validator.engine.primitives import (
    NumericPrefs,
    check_any,
    check_boolean,
    check_color,
    check_coordinate,
    check_decimal,
    check_integer,
    check_orientation,
    check_position,
    validate_constraint,
)

DEFAULT = NumericPrefs()
STRICT_INT = NumericPrefs(integer_strict=True)
NO_INT_DECIMAL = NumericPrefs(decimal_allow_integer=False)


def _value(text: str):
    """Parse ``k <text>`` and return the value of the node.

    Args:
        text: Value text.

    Returns:
        The parsed value.

    Raises:
        AssertionError: If the line does not parse.
    """
    node = parse(f"TXT\nk {text}\n").nodes[0]
    assert node.value is not None
    return node.value


@pytest.mark.parametrize("text", ["TRUE", "FALSE"])
def test_boolean_accepts_true_and_false(text: str) -> None:
    assert check_boolean(_value(text), DEFAULT).ok


@pytest.mark.parametrize("text", ['"TRUE"', "1", "0.000000", "[ 1 , 2 ]", "ffffffff"])
def test_boolean_rejects_other_shapes(text: str) -> None:
    result = check_boolean(_value(text), DEFAULT)
    assert not result.ok and result.message


def test_boolean_rejects_lowercase_spelling() -> None:
    # "true" is not TRUE/FALSE, so the parser cannot produce a BoolValue; it
    # is rejected at parse time and no node is produced.
    assert parse("TXT\nk true\n").nodes == []


@pytest.mark.parametrize("text", ["0", "42", "-3", "194"])
def test_integer_accepts_integer_form(text: str) -> None:
    assert check_integer(_value(text), STRICT_INT).ok


@pytest.mark.parametrize("text", ["0.000000", "-1.500000", ".5", "-.111111"])
def test_integer_accepts_decimal_form_unless_strict(text: str) -> None:
    assert check_integer(_value(text), DEFAULT).ok
    assert not check_integer(_value(text), STRICT_INT).ok


@pytest.mark.parametrize("text", ['"5"', "TRUE", "[ 1 , 2 ]", "ffffffff", "1e5", "+5", "5."])
def test_integer_rejects_other_shapes(text: str) -> None:
    node = parse(f"TXT\nk {text}\n").nodes[0]
    assert node.value is not None
    assert not check_integer(node.value, DEFAULT).ok


@pytest.mark.parametrize("text", ["0.000000", "-1.500000", ".5", "-.111111", "12.0"])
def test_decimal_accepts_decimal_form(text: str) -> None:
    assert check_decimal(_value(text), NO_INT_DECIMAL).ok


@pytest.mark.parametrize("text", ["0", "42", "-3"])
def test_decimal_integer_form_depends_on_preference(text: str) -> None:
    assert check_decimal(_value(text), DEFAULT).ok
    assert not check_decimal(_value(text), NO_INT_DECIMAL).ok


@pytest.mark.parametrize(
    "text", ['"1.0"', "FALSE", "[ 0.0 , 1.0 ]", "ffffffff", "1e5", "+1.0", "1."]
)
def test_decimal_rejects_other_shapes(text: str) -> None:
    assert not check_decimal(_value(text), DEFAULT).ok


@pytest.mark.parametrize("text", ['"x"', "1", "TRUE", "[ 1 , 2 ]", "ffffffff"])
def test_any_accepts_everything(text: str) -> None:
    assert check_any(_value(text), DEFAULT).ok


@pytest.mark.parametrize("text", ["1e3", "+1", "5.", "-5.", "1E3", "+.5"])
def test_numbers_reject_exponent_plus_and_trailing_point(text: str) -> None:
    assert not check_integer(_value(text), DEFAULT).ok
    assert not check_decimal(_value(text), DEFAULT).ok


@pytest.mark.parametrize("text", [".5", "-.5", "-3", "0.000000"])
def test_numbers_accept_leading_dot_and_negatives(text: str) -> None:
    assert check_integer(_value(text), DEFAULT).ok
    assert check_decimal(_value(text), DEFAULT).ok


@pytest.mark.parametrize(
    "text",
    [
        "ffffffff",
        "FFFFFFFF",
        "80ff00aa",
        "00000000",
        "12345678",
        "0",
        "a1b2c3",
        "123456",
        "ff00",
        "1e30",
    ],
)
def test_color_accepts_surveyed_shapes(text: str) -> None:
    assert check_color(_value(text), DEFAULT).ok


@pytest.mark.parametrize(
    "text",
    [
        "fffffff",  # 7 digits
        "fffff",  # 5 digits
        "fffffffff",  # 9 digits
        "ff",  # 2 digits
        "00",  # not the lone 0
        "ffffffgg",  # non-hex trailing characters (the plugin never checks them)
    ],
)
def test_color_rejects_other_lengths_and_non_hex(text: str) -> None:
    node = parse(f"TXT\nk {text}\n").nodes
    # Non-hex tokens do not parse at all, which is also a rejection.
    if node and node[0].value is not None:
        assert not check_color(node[0].value, DEFAULT).ok
    else:
        assert not node


@pytest.mark.parametrize("text", ['"ffffffff"', '"0"', "0x1234", "TRUE", "[ 1 , 2 ]", "-1", "1.5"])
def test_color_rejects_prefix_quotes_and_other_kinds(text: str) -> None:
    node = parse(f"TXT\nk {text}\n").nodes
    if node and node[0].value is not None:
        assert not check_color(node[0].value, DEFAULT).ok
    else:
        assert not node


@pytest.mark.parametrize(
    ("text", "constraint"),
    [
        ("[ 234 , 219 ]", "count=2"),
        ("[ 0 , 0 ]", "count=2"),
        ("[ -12 , 40 ]", "count=2"),
        ("[ 0 , 0 , 640 , 480 ]", "count=4"),
        ("[9, 99, 999, 99]", "count=4"),
        ("[ -4 , 0 , 8 , -2 ]", "count=4"),
    ],
)
def test_position_accepts_surveyed_shapes(text: str, constraint: str) -> None:
    assert check_position(_value(text), DEFAULT, constraint).ok


@pytest.mark.parametrize(
    ("text", "constraint"),
    [
        ("[ 0 , 0 , 640 , 480 ]", "count=2"),  # 4 items where pos has 2
        ("[ 234 , 219 ]", "count=4"),  # 2 items where pixelBox has 4
        ("[ 234 ]", "count=2"),
        ("[ ]", "count=2"),
        ("[ 1 2 ]", "count=2"),  # space separated
        ("[ 1.5 , 2 ]", "count=2"),  # decimal
        ("[ 1e2 , 2 ]", "count=2"),
        ("[ +1 , 2 ]", "count=2"),
        ('"[ 1 , 2 ]"', "count=2"),
        ("5", "count=2"),
        ("[ 0.1 0.2 0.3 ]", "count=3"),
    ],
)
def test_position_rejects_other_shapes(text: str, constraint: str) -> None:
    node = parse(f"TXT\nk {text}\n").nodes[0]
    assert node.value is not None
    assert not check_position(node.value, DEFAULT, constraint).ok


def test_position_without_constraint_checks_shape_only() -> None:
    assert check_position(_value("[ 1 , 2 , 3 ]"), DEFAULT).ok
    assert not check_position(_value("[ 1 2 ]"), DEFAULT).ok
    assert not check_position(_value("[ 1.5 , 2 ]"), DEFAULT).ok


@pytest.mark.parametrize("bad", ["count=0", "count=-1", "count=x", "4", ">0", "count=2 "])
def test_position_malformed_constraint_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        check_position(_value("[ 1 , 2 ]"), DEFAULT, bad)


def test_validate_constraint() -> None:
    assert validate_constraint("Position", None) is None
    assert validate_constraint("Position", "count=4") is None
    assert validate_constraint("Position", "count=0")
    assert validate_constraint("Decimal", ">0")
    assert validate_constraint("Integer", "count=2")


@pytest.mark.parametrize(
    "text",
    [
        "[ 0.000000 0.100000 0.000000 ]",
        "[ -1.000000 0.500000 -0.250000 ]",
        "[ .5 -.5 1 ]",
        "[0.0 1.0 2.0]",
    ],
)
def test_coordinate_accepts_three_space_separated_numbers(text: str) -> None:
    assert check_coordinate(_value(text), DEFAULT).ok


@pytest.mark.parametrize(
    "text",
    [
        "[ 0.0 1.0 ]",  # 2 items
        "[ 0.0 1.0 2.0 3.0 ]",  # 4 items
        "[ 0.0 , 1.0 , 2.0 ]",  # comma separated
        "[ ]",
        "[ 1e3 0.0 0.0 ]",
        "[ +1.0 0.0 0.0 ]",
        "[ 1. 0.0 0.0 ]",
        "0.5",
        '"[ 0.0 1.0 2.0 ]"',
    ],
)
def test_coordinate_rejects_other_shapes(text: str) -> None:
    node = parse(f"TXT\nk {text}\n").nodes[0]
    assert node.value is not None
    assert not check_coordinate(node.value, DEFAULT).ok


ROW = "\t[ 1.000000 0.000000 0.000000 ]"


def _orientation(*rows: str, header: str = "Orientation") -> Node:
    """Parse a header followed by tab-indented keyless rows.

    Args:
        *rows: Row lines, each already tab-indented.
        header: Header line.

    Returns:
        The header node.

    Raises:
        AssertionError: If the text does not parse to a single header.
    """
    p = parse("TXT\n" + header + "\n" + "\n".join(rows) + "\nnext 1\n")
    assert p.nodes[-1].key == "next"
    return p.nodes[0]


def test_orientation_accepts_header_with_three_coordinate_rows() -> None:
    node = _orientation(
        ROW, "\t[ 0.000000 -1.000000 0.000000 ]", "\t[ 0.000000 0.000000 1.000000 ]"
    )
    assert check_orientation(node, DEFAULT).ok


def test_orientation_rejects_two_rows() -> None:
    assert not check_orientation(_orientation(ROW, ROW), DEFAULT).ok


def test_orientation_rejects_four_rows() -> None:
    assert not check_orientation(_orientation(ROW, ROW, ROW, ROW), DEFAULT).ok


def test_orientation_rejects_a_bad_row() -> None:
    result = check_orientation(_orientation(ROW, "\t[ 1.0 0.0 ]", ROW), DEFAULT)
    assert not result.ok and result.message and "Row 2" in result.message


def test_orientation_rejects_comma_separated_row() -> None:
    assert not check_orientation(_orientation(ROW, ROW, "\t[ 1.0 , 0.0 , 0.0 ]"), DEFAULT).ok


def test_orientation_rejects_header_with_a_value() -> None:
    p = parse("TXT\nOrientation [ 1.0 0.0 0.0 ]\n")
    assert not check_orientation(p.nodes[0], DEFAULT).ok


def test_orientation_rejects_keyed_rows() -> None:
    p = parse("TXT\nOrientation\n\ta [ 1.0 0.0 0.0 ]\n\tb [ 1.0 0.0 0.0 ]\n\tc [ 1.0 0.0 0.0 ]\n")
    assert not check_orientation(p.nodes[0], DEFAULT).ok


def test_particle_style_block_checks_end_to_end() -> None:
    text = (
        "TXT2\nPosition [ 0.000000 -0.500000 0.000000 ]\nOrientation\n"
        "\t[ 1.000000 0.000000 0.000000 ]\n\t[ 0.000000 1.000000 0.000000 ]\n"
        "\t[ 0.000000 0.000000 1.000000 ]\nParticleStartColor ffffffff\n"
    )
    p = parse(text)
    assert not p.diagnostics
    position, orientation, color = p.nodes
    assert position.value is not None and color.value is not None
    assert check_coordinate(position.value, DEFAULT).ok
    assert check_orientation(orientation, DEFAULT).ok
    assert check_color(color.value, DEFAULT).ok
