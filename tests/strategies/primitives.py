"""Hypothesis strategies for primitive checker inputs.

Values are built directly (not parsed) so each strategy states the exact
token shape under test. Accepted and rejected shapes follow design.md,
"Validator" > "Primitive rules and evidence" (Rebellion 1.98 evidence):

* numbers: integers, decimals with a digit before the point, leading-point
  decimals, negatives; exponents, a leading ``+`` and a trailing point are
  rejected;
* Color: 8, 6 or 4 hex digits in any case, or a lone ``0``;
* Position: bracketed comma separated integers with ``count=N``;
* Coordinate: exactly 3 numbers, whitespace separated;
* Orientation: value-less header with exactly 3 keyless Coordinate rows.
"""

from __future__ import annotations

from hypothesis import strategies as st

from soase_validator.engine.model import Span
from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    ListValue,
    Node,
    NumberValue,
    StringValue,
    Value,
)

_DIGITS = "0123456789"
_HEX = "0123456789abcdefABCDEF"
_SIGN = st.sampled_from(["", "-"])
_UNSIGNED_INT = st.text(alphabet=_DIGITS, min_size=1, max_size=8)
_FRACTION = st.text(alphabet=_DIGITS, min_size=1, max_size=8)

#: Integer form, for example ``42`` or ``-3``.
integer_texts: st.SearchStrategy[str] = st.builds(lambda s, d: s + d, _SIGN, _UNSIGNED_INT)

#: Decimal form with a digit before the point, for example ``-1.500000``.
pointed_decimal_texts: st.SearchStrategy[str] = st.builds(
    lambda s, i, f: f"{s}{i}.{f}", _SIGN, _UNSIGNED_INT, _FRACTION
)

#: Leading-point decimal form, for example ``.5`` or ``-.111111``.
leading_dot_texts: st.SearchStrategy[str] = st.builds(lambda s, f: f"{s}.{f}", _SIGN, _FRACTION)

#: Any decimal form.
decimal_texts: st.SearchStrategy[str] = st.one_of(pointed_decimal_texts, leading_dot_texts)

#: Any accepted number form.
number_texts: st.SearchStrategy[str] = st.one_of(integer_texts, decimal_texts)

#: Near-miss number tokens: built from a good number by adding a rejected part.
bad_number_texts: st.SearchStrategy[str] = st.one_of(
    st.builds(lambda t: "+" + t, number_texts),
    st.builds(lambda t: t + ".", integer_texts),
    st.builds(
        lambda t, e, s, d: f"{t}{e}{s}{d}",
        number_texts,
        st.sampled_from(["e", "E"]),
        st.sampled_from(["", "+", "-"]),
        _UNSIGNED_INT,
    ),
    st.builds(lambda t: "-" + t, st.builds(lambda s: "-" + s, integer_texts)),
    st.builds(lambda a, b: f"{a}.{b}.{a}", _UNSIGNED_INT, _UNSIGNED_INT),
    st.sampled_from(["", "-", ".", "-.", "+", "e5", "0x10", "1,5", "1_0", "1 2"]),
)


def number_value(text: str) -> NumberValue:
    """Wrap number text in a ``NumberValue``, keeping the raw token.

    Args:
        text: Token text.

    Returns:
        A ``NumberValue`` whose ``raw`` is ``text``.

    Raises:
        None.
    """
    try:
        value: int | float = int(text)
    except ValueError:
        value = 0.0
    return NumberValue(raw=text, value=value)


def _list(texts: list[str], separator: str) -> ListValue:
    """Build a ``ListValue`` from item texts.

    Args:
        texts: Item token texts.
        separator: ``","`` or ``" "``.

    Returns:
        The list value.

    Raises:
        None.
    """
    return ListValue(items=tuple(number_value(t) for t in texts), separator=separator)


#: Values that are never a plain number token.
non_number_values: st.SearchStrategy[Value] = st.one_of(
    st.builds(StringValue, st.text(max_size=6)),
    st.builds(BoolValue, st.booleans()),
    st.builds(_list, st.lists(integer_texts, min_size=1, max_size=3), st.just(",")),
    st.builds(HexValue, st.text(alphabet="abcdef", min_size=1, max_size=8)),
)

#: Values that are not booleans.
non_boolean_values: st.SearchStrategy[Value] = st.one_of(
    st.builds(number_value, number_texts),
    st.builds(StringValue, st.sampled_from(["TRUE", "FALSE", "true", ""])),
    st.builds(HexValue, st.text(alphabet="abcdef", min_size=1, max_size=8)),
    st.builds(_list, st.lists(integer_texts, min_size=1, max_size=3), st.just(",")),
)


def color_value(text: str) -> Value:
    """Wrap a color token the way the parser does.

    Args:
        text: Token text.

    Returns:
        ``NumberValue`` for all-digit tokens, otherwise ``HexValue``.

    Raises:
        None.
    """
    if text.isdigit():
        return number_value(text)
    return HexValue(raw=text)


#: Accepted color tokens: 8, 6 or 4 hex digits in any case, or a lone ``0``.
color_texts: st.SearchStrategy[str] = st.one_of(
    st.sampled_from([4, 6, 8]).flatmap(lambda n: st.text(alphabet=_HEX, min_size=n, max_size=n)),
    st.just("0"),
)

#: Rejected color tokens: wrong length, ``0x`` prefix, or a non-hex character.
bad_color_texts: st.SearchStrategy[str] = st.one_of(
    st.integers(min_value=1, max_value=14)
    .filter(lambda n: n not in (4, 6, 8))
    .flatmap(lambda n: st.text(alphabet=_HEX, min_size=n, max_size=n))
    .filter(lambda t: t != "0"),
    st.builds(
        lambda p, t: p + t,
        st.sampled_from(["0x", "0X"]),
        st.sampled_from([4, 6, 8]).flatmap(
            lambda n: st.text(alphabet=_HEX, min_size=n, max_size=n)
        ),
    ),
    st.sampled_from([8, 6, 4]).flatmap(
        lambda n: st.builds(
            lambda head, bad, pos: head[:pos] + bad + head[pos + 1 :],
            st.text(alphabet=_HEX, min_size=n, max_size=n),
            st.sampled_from(list("gGzZ-.+ ")),
            st.integers(min_value=0, max_value=n - 1),
        )
    ),
)

#: Colors written in quotes are a ``StringValue`` and are rejected.
quoted_color_values: st.SearchStrategy[Value] = st.builds(
    lambda t: StringValue(text=t), color_texts
)

#: Position item counts used by Definitions (``count=N``).
position_counts: st.SearchStrategy[int] = st.integers(min_value=1, max_value=8)


def position_value(items: list[str], separator: str = ",") -> ListValue:
    """Build a Position list value.

    Args:
        items: Item token texts.
        separator: List separator.

    Returns:
        The list value.

    Raises:
        None.
    """
    return _list(items, separator)


#: Malformed ``constraint`` strings for a ``Position`` field.
malformed_constraints: st.SearchStrategy[str] = st.one_of(
    st.sampled_from(["", "count=", "count=0", "count=-1", "count=x", "count=2.5", "foo", "N=2"]),
    st.builds(lambda n: f"count={n} ", position_counts),
    st.builds(lambda n: f" count={n}", position_counts),
    st.builds(lambda n: f"COUNT={n}", position_counts),
    st.builds(lambda n: f"count={n};", position_counts),
)

#: Validation types that take no constraint.
unconstrained_types: st.SearchStrategy[str] = st.sampled_from(
    ["Boolean", "Integer", "Decimal", "Color", "Coordinate", "Orientation", "Any"]
)


def coordinate_value(texts: list[str], separator: str = " ") -> ListValue:
    """Build a Coordinate list value.

    Args:
        texts: Item token texts.
        separator: List separator, space by default.

    Returns:
        The list value.

    Raises:
        None.
    """
    return _list(texts, separator)


#: Exactly three accepted number texts.
coordinate_item_texts: st.SearchStrategy[list[str]] = st.lists(number_texts, min_size=3, max_size=3)


def keyless_row(value: Value | None, key: str = "") -> Node:
    """Build a row node for an Orientation.

    Args:
        value: The row value.
        key: Row key; empty for a keyless row.

    Returns:
        The node.

    Raises:
        None.
    """
    return Node(key=key, key_span=Span(0, 0, 0, 0), value=value)


def orientation_header(rows: list[Node], value: Value | None = None) -> Node:
    """Build an Orientation header node.

    Args:
        rows: Child rows.
        value: Header value; None for the accepted shape.

    Returns:
        The header node with ``rows`` as children.

    Raises:
        None.
    """
    header = Node(key="orientation", key_span=Span(0, 0, 0, 0), value=value)
    header.children = list(rows)
    return header
