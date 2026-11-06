"""Pure checkers for primitive validation types.

Each ``check_<type>`` function takes the parsed value, the numeric
preferences and the field's ``constraint`` string from the Definition, and
returns a ``PrimitiveResult``. ``check_orientation`` takes the header
``Node`` instead of a value, because an ``Orientation`` is a block whose rows
are children. The checkers have no side effects. Reference types are not
primitives and are handled elsewhere.

The checkers accept exactly the shapes the Rebellion 1.98 reference files
use and reject everything else. In several places this is deliberately
stricter than the zombiesrus5 plugin (see "Differences from the plugin").

Evidence (Rebellion 1.98 reference files, shapes and counts only)
-----------------------------------------------------------------
Boolean
    Only ``TRUE`` and ``FALSE`` occur (68956 uses, 228 contexts). No other
    spelling or case variant occurs.
Integer and Decimal number forms
    Plain integers (``42``, ``-3``), decimals with a digit before the point
    (``0.000000``, ``-1.5``) and decimals with no digit before the point
    (``.5``, ``-.111111``) occur. A leading ``+``, an exponent and a
    trailing point (``5.``) do not occur, so they are rejected.
Integer fields written as decimals
    Integer fields hold decimal forms in real files (``dec6`` 199 uses in 15
    contexts, ``dec1`` 106, ``leading-dot1`` 22), so the default accepts
    them. ``integer_strict`` rejects the decimal point.
Decimal fields written as integers
    Decimal fields hold integer forms in real files (666 uses in 84
    contexts), so ``decimal_allow_integer`` defaults to True.
Color
    4208 uses in 34 contexts: 8 hex digits (4109 lowercase, 1 uppercase),
    a lone ``0`` (94), 6 hex digits (3) and 4 hex digits (1). All are
    unquoted. No ``0x`` prefix occurs in Colors. The parser yields a
    ``NumberValue`` for all-digit tokens (``0``, ``00000000``) and a
    ``HexValue`` otherwise, so the raw token text is checked.
Position
    14699 uses in 13 contexts, always a bracketed, comma separated list of
    integers (negatives occur, decimals do not). The item count is fixed per
    field: 2 for ``pos`` (``.galaxy`` star and planet, ``ResearchSubject``
    ``researchWindowLocation``) and 4 for ``pixelBox`` (``.brushes``),
    ``area`` (``Player`` research screen blocks) and
    ``mainViewIconAreaOffsetFromCenter`` (``PipCloud``). The count lives in
    the Definition as ``constraint`` ``count=N``.
Coordinate
    7876 uses in 11 contexts (``.particle``), always a bracketed,
    space separated list of exactly 3 numbers (six-place decimals,
    negatives). Integer items do not occur; they are accepted by user
    decision, to match the plugin (``BigDecimal`` items).
Orientation
    3625 uses in 3 contexts (``.particle``): a header with no value and
    exactly 3 keyless child rows, each a Coordinate.

Differences from the plugin (the reference files are the authority)
-------------------------------------------------------------------
* Color: every digit is checked (the plugin skips trailing characters),
  quotes are not stripped (the plugin blanks them) and a ``0x`` prefix is
  rejected.
* Position, Coordinate: the item count is enforced (the plugin counts
  nothing).
* Numbers: exponents, a leading ``+`` and a trailing point are rejected (the
  plugin uses ``BigDecimal`` and accepts them).
* Quotes are not stripped before checking numbers (the plugin blanks them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    ListValue,
    Node,
    NumberValue,
    StringValue,
    Value,
)

_INTEGER_FORM = re.compile(r"-?\d+")
_DECIMAL_FORM = re.compile(r"-?(?:\d+\.\d+|\.\d+)")
_COLOR_FORM = re.compile(r"0|[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{4}")
_COUNT_CONSTRAINT = re.compile(r"count=([1-9]\d*)")

#: Orientation rows, fixed by the reference files.
ORIENTATION_ROWS = 3
#: Coordinate items, fixed by the reference files.
COORDINATE_ITEMS = 3

#: Validation types that accept a ``constraint`` in a Definition.
CONSTRAINED_TYPES = frozenset({"Position"})


@dataclass(frozen=True, slots=True)
class NumericPrefs:
    """Numeric strictness settings.

    Attributes:
        integer_strict: Reject ``Integer`` values written with a decimal
            point.
        decimal_allow_integer: Accept integer-form values (no decimal point)
            for ``Decimal`` fields.
    """

    integer_strict: bool = False
    decimal_allow_integer: bool = True


@dataclass(frozen=True, slots=True)
class PrimitiveResult:
    """Outcome of a primitive check.

    Attributes:
        ok: True when the value conforms to the type.
        message: Human-readable reason when ``ok`` is False, else None.
    """

    ok: bool
    message: str | None = None


_OK = PrimitiveResult(True)


def _bad(message: str) -> PrimitiveResult:
    """Build a failing result.

    Args:
        message: Reason the value is rejected.

    Returns:
        A result with ``ok`` False.

    Raises:
        None.
    """
    return PrimitiveResult(False, message)


def _describe(raw: Value) -> str:
    """Name the kind of a value for messages.

    Args:
        raw: The parsed value.

    Returns:
        A short phrase such as ``a quoted string``.

    Raises:
        None.
    """
    match raw:
        case StringValue():
            return "a quoted string"
        case NumberValue():
            return f"the number {raw.raw}"
        case BoolValue():
            return "a boolean"
        case ListValue():
            return "a list"
        case HexValue():
            return f"the token {raw.raw}"


def validate_constraint(validation: str, constraint: str | None) -> str | None:
    """Check a Definition ``constraint`` against its validation type.

    Only ``Position`` takes a constraint, in the form ``count=N`` with ``N`` a
    positive integer.

    Args:
        validation: Validation type of the field.
        constraint: The constraint text, or None.

    Returns:
        None when the constraint is absent or valid, otherwise a message.

    Raises:
        None.
    """
    if constraint is None:
        return None
    if validation not in CONSTRAINED_TYPES:
        return f"Validation type {validation} takes no constraint, found {constraint!r}"
    if not _COUNT_CONSTRAINT.fullmatch(constraint):
        return f"Constraint must be count=N with N a positive integer, found {constraint!r}"
    return None


def check_boolean(
    raw: Value, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check a ``Boolean`` value (``TRUE`` or ``FALSE``).

    Args:
        raw: The parsed value.
        prefs: Numeric preferences (unused).
        constraint: Definition constraint (unused).

    Returns:
        An ok result for ``BoolValue``, otherwise a failure.

    Raises:
        None.
    """
    if isinstance(raw, BoolValue):
        return _OK
    return _bad(f"Expected TRUE or FALSE, found {_describe(raw)}")


def check_integer(
    raw: Value, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check an ``Integer`` value.

    Accepts integer form and, unless ``integer_strict`` is set, decimal form.
    Exponents, a leading ``+`` and a trailing point are rejected.

    Args:
        raw: The parsed value.
        prefs: Numeric preferences.
        constraint: Definition constraint (unused).

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        None.
    """
    if not isinstance(raw, NumberValue):
        return _bad(f"Expected an integer, found {_describe(raw)}")
    if _INTEGER_FORM.fullmatch(raw.raw):
        return _OK
    if _DECIMAL_FORM.fullmatch(raw.raw):
        if prefs.integer_strict:
            return _bad(f"Expected an integer without a decimal point, found {raw.raw}")
        return _OK
    return _bad(f"Expected an integer, found {_describe(raw)}")


def check_decimal(
    raw: Value, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check a ``Decimal`` value.

    Accepts decimal form and, when ``decimal_allow_integer`` is set, integer
    form. Exponents, a leading ``+`` and a trailing point are rejected.

    Args:
        raw: The parsed value.
        prefs: Numeric preferences.
        constraint: Definition constraint (unused).

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        None.
    """
    if not isinstance(raw, NumberValue):
        return _bad(f"Expected a decimal number, found {_describe(raw)}")
    if _DECIMAL_FORM.fullmatch(raw.raw):
        return _OK
    if _INTEGER_FORM.fullmatch(raw.raw):
        if prefs.decimal_allow_integer:
            return _OK
        return _bad(f"Expected a decimal with a decimal point, found {raw.raw}")
    return _bad(f"Expected a decimal number, found {_describe(raw)}")


def check_color(raw: Value, prefs: NumericPrefs, constraint: str | None = None) -> PrimitiveResult:
    """Check a ``Color`` value.

    Accepts an unquoted token of exactly 8, 6 or 4 hexadecimal digits in any
    letter case, or a lone ``0``. Every digit is checked. A ``0x`` prefix and
    quoted values are rejected.

    Args:
        raw: The parsed value. The raw token text is used because the parser
            yields ``NumberValue`` for all-digit tokens and ``HexValue``
            otherwise.
        prefs: Numeric preferences (unused).
        constraint: Definition constraint (unused).

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        None.
    """
    if isinstance(raw, NumberValue | HexValue):
        if _COLOR_FORM.fullmatch(raw.raw):
            return _OK
        return _bad(
            f"Expected a color of 8, 6 or 4 hex digits or 0, found {raw.raw}",
        )
    return _bad(f"Expected a color of 8, 6 or 4 hex digits or 0, found {_describe(raw)}")


def _check_integer_list(raw: ListValue) -> str | None:
    """Check that every list item is written as an integer.

    Args:
        raw: The list.

    Returns:
        A message naming the first bad item, or None.

    Raises:
        None.
    """
    for item in raw.items:
        if not _INTEGER_FORM.fullmatch(item.raw):
            return f"Expected integers, found {item.raw}"
    return None


def check_position(
    raw: Value, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check a ``Position`` value.

    A bracketed, comma separated list of integers. The item count is taken
    from ``constraint`` (``count=N``); without a constraint the count is not
    checked.

    Args:
        raw: The parsed value.
        prefs: Numeric preferences (unused).
        constraint: Definition constraint, ``count=N`` or None.

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        ValueError: If ``constraint`` is malformed (see
            :func:`validate_constraint`).
    """
    problem = validate_constraint("Position", constraint)
    if problem:
        raise ValueError(problem)
    if not isinstance(raw, ListValue):
        return _bad(f"Expected a bracketed list of integers, found {_describe(raw)}")
    if raw.separator != ",":
        return _bad("Expected comma separated integers, found a space separated list")
    message = _check_integer_list(raw)
    if message:
        return _bad(message)
    match = _COUNT_CONSTRAINT.fullmatch(constraint) if constraint is not None else None
    if match is not None and len(raw.items) != int(match.group(1)):
        return _bad(f"Expected {match.group(1)} integers, found {len(raw.items)}")
    return _OK


def check_coordinate(
    raw: Value, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check a ``Coordinate`` value.

    A bracketed, space separated list of exactly 3 numbers. Exponents, a
    leading ``+`` and a trailing point are rejected.

    Args:
        raw: The parsed value.
        prefs: Numeric preferences (unused).
        constraint: Definition constraint (unused).

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        None.
    """
    if not isinstance(raw, ListValue):
        return _bad(f"Expected a bracketed list of 3 numbers, found {_describe(raw)}")
    if raw.separator == "," and len(raw.items) > 1:
        return _bad("Expected space separated numbers, found a comma separated list")
    if len(raw.items) != COORDINATE_ITEMS:
        return _bad(f"Expected {COORDINATE_ITEMS} numbers, found {len(raw.items)}")
    for item in raw.items:
        if not (_INTEGER_FORM.fullmatch(item.raw) or _DECIMAL_FORM.fullmatch(item.raw)):
            return _bad(f"Expected numbers, found {item.raw}")
    return _OK


def check_orientation(
    node: Node, prefs: NumericPrefs, constraint: str | None = None
) -> PrimitiveResult:
    """Check an ``Orientation`` block.

    A header with no value and exactly 3 keyless child rows, each a
    ``Coordinate``.

    Args:
        node: The header node; its children are the rows.
        prefs: Numeric preferences (unused).
        constraint: Definition constraint (unused).

    Returns:
        An ok result, or a failure with the reason.

    Raises:
        None.
    """
    if node.value is not None:
        return _bad("Expected an Orientation header with no value")
    rows = node.children
    if len(rows) != ORIENTATION_ROWS:
        return _bad(f"Expected {ORIENTATION_ROWS} rows, found {len(rows)}")
    for number, row in enumerate(rows, start=1):
        if row.key or row.children or row.value is None:
            return _bad(f"Row {number} must be a bracketed list of 3 numbers")
        result = check_coordinate(row.value, prefs)
        if not result.ok:
            return _bad(f"Row {number}: {result.message}")
    return _OK


def check_any(raw: Value, prefs: NumericPrefs, constraint: str | None = None) -> PrimitiveResult:
    """Check an ``Any`` value, which places no constraint on the value.

    Args:
        raw: The parsed value (unused).
        prefs: Numeric preferences (unused).
        constraint: Definition constraint (unused).

    Returns:
        Always an ok result.

    Raises:
        None.
    """
    return _OK


__all__ = [
    "CONSTRAINED_TYPES",
    "COORDINATE_ITEMS",
    "ORIENTATION_ROWS",
    "NumericPrefs",
    "PrimitiveResult",
    "check_any",
    "check_boolean",
    "check_color",
    "check_coordinate",
    "check_decimal",
    "check_integer",
    "check_orientation",
    "check_position",
    "validate_constraint",
]
