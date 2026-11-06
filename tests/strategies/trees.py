"""Hypothesis strategies and a renderer for parser trees.

``trees()`` generates lists of ``GenNode`` (the expected tree), including
strings (empty too), six-place decimals, booleans, hexadecimal tokens,
comma and whitespace separated bracket lists, keyless list rows under a
header, keys with colons, nested blocks and count-prefixed repeats. ``indent_style`` generates
per-depth indentation prefixes (tabs, spaces or a mix) whose widths strictly
increase with depth. ``render_tree`` turns a generated tree into file text and
``matches_parsed`` compares it with the parser's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hypothesis import strategies as st

from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    ListValue,
    Node,
    NumberValue,
    StringValue,
    Value,
    _format_value,
    _number,
)

MAX_DEPTH = 4
"""Deepest nesting level the strategies generate (top level is depth 0)."""

_RESERVED_KEYS = frozenset({"SinsArchiveVersion", "TXT", "TXT2"})
_KEY_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_KEY_REST = _KEY_START + "0123456789_:"


@dataclass(slots=True)
class GenNode:
    """A generated tree node: the expected parse result for one line.

    Attributes:
        key: Key text (no whitespace, may contain colons). Empty for a
            keyless list row.
        value: Value, or None for block keys.
        children: Nested nodes (only for block keys).
    """

    key: str
    value: Value | None = None
    children: list[GenNode] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IndentStyle:
    """Indentation prefix for each nesting depth.

    Attributes:
        prefixes: ``prefixes[d]`` is the indentation for depth ``d``. The
            first is empty and each is a strict extension of the previous,
            so widths strictly increase.
    """

    prefixes: tuple[str, ...]

    def for_depth(self, depth: int) -> str:
        """Return the indentation for a depth.

        Args:
            depth: Zero-based nesting depth.

        Returns:
            The indentation text.

        Raises:
            IndexError: If ``depth`` exceeds ``MAX_DEPTH``.
        """
        return self.prefixes[depth]


TAB_INDENT = IndentStyle(tuple("\t" * d for d in range(MAX_DEPTH + 1)))
"""One tab per level (the canonical style of ``format_tree``)."""


# ---------------------------------------------------------------- values

_keys = st.builds(
    lambda head, rest: head + rest,
    st.sampled_from(_KEY_START),
    st.text(alphabet=_KEY_REST, max_size=10),
).filter(lambda k: k not in _RESERVED_KEYS)

_string_text = st.text(
    alphabet=st.characters(
        blacklist_characters='"\r\n',
        blacklist_categories=("Cs", "Cc"),
    ),
    max_size=12,
)
_strings = st.builds(StringValue, _string_text)


def _int_value(n: int) -> NumberValue:
    """Build an integer ``NumberValue``.

    Args:
        n: The integer.

    Returns:
        The value with canonical raw text.

    Raises:
        None.
    """
    return NumberValue(str(n), n)


def _decimal_value(n: int) -> NumberValue:
    """Build a six-place decimal ``NumberValue`` from micro-units.

    Args:
        n: The value multiplied by 1,000,000.

    Returns:
        The value written with exactly six decimal places.

    Raises:
        None.
    """
    sign = "-" if n < 0 else ""
    whole, frac = divmod(abs(n), 1_000_000)
    raw = f"{sign}{whole}.{frac:06d}"
    return NumberValue(raw, float(raw))


_integers = st.integers(-10_000, 10_000).map(_int_value)
_decimals = st.integers(-10_000_000_000, 10_000_000_000).map(_decimal_value)
_numbers = st.one_of(_integers, _decimals)
_bools = st.booleans().map(BoolValue)
_comma_lists = st.lists(_numbers, max_size=4).map(lambda xs: ListValue(tuple(xs)))
_space_lists = st.lists(_decimals, min_size=2, max_size=4).map(lambda xs: ListValue(tuple(xs), " "))
_lists = st.one_of(_comma_lists, _space_lists)
_hex_values = (
    st.text(alphabet="0123456789abcdefABCDEF", min_size=1, max_size=8)
    .filter(lambda s: _number(s) is None)
    .map(HexValue)
)
_values: st.SearchStrategy[Value] = st.one_of(_strings, _numbers, _bools, _lists, _hex_values)


# ----------------------------------------------------------------- trees

_leaves = st.builds(lambda k, v: [GenNode(k, v)], _keys, _values)


def _blocks(
    children: st.SearchStrategy[list[GenNode]],
) -> st.SearchStrategy[list[GenNode]]:
    """Build a strategy for a single block node wrapping child groups.

    Args:
        children: Strategy for a flat list of child nodes.

    Returns:
        A strategy yielding a one-element node list.

    Raises:
        None.
    """
    return st.builds(lambda k, c: [GenNode(k, None, c)], _keys, children)


def _repeats(
    children: st.SearchStrategy[list[GenNode]],
) -> st.SearchStrategy[list[GenNode]]:
    """Build a strategy for a count-prefixed repeat group.

    The group is ``<name>Count N`` followed by N sibling ``<name>`` blocks.

    Args:
        children: Strategy for the body of each repeated block.

    Returns:
        A strategy yielding the count node followed by the repeated nodes.

    Raises:
        None.
    """

    def build(name: str, bodies: list[list[GenNode]]) -> list[GenNode]:
        nodes = [GenNode(f"{name}Count", _int_value(len(bodies)))]
        nodes.extend(GenNode(name, None, body) for body in bodies)
        return nodes

    return st.builds(
        build,
        st.text(alphabet=_KEY_START, min_size=1, max_size=8),
        st.lists(children, max_size=3),
    )


def _groups(
    inner: st.SearchStrategy[list[GenNode]],
) -> st.SearchStrategy[list[GenNode]]:
    """Combine groups into a flat sibling list (children of a block).

    Args:
        inner: Strategy for one group of sibling nodes.

    Returns:
        A strategy yielding a flattened list of nodes.

    Raises:
        None.
    """
    return st.lists(inner, max_size=4).map(lambda gs: [n for g in gs for n in g])


def _orientations() -> st.SearchStrategy[list[GenNode]]:
    """Build a strategy for a header block whose children are keyless rows.

    Returns:
        A strategy yielding a one-element node list: a block with three
        keyless whitespace separated rows.

    Raises:
        None.
    """
    row = st.lists(_decimals, min_size=3, max_size=3).map(
        lambda xs: GenNode("", ListValue(tuple(xs), " "))
    )
    return st.builds(
        lambda k, rows: [GenNode(k, None, rows)],
        _keys,
        st.lists(row, min_size=1, max_size=3),
    )


def _group_at_depth(depth: int) -> st.SearchStrategy[list[GenNode]]:
    """Build the group strategy for nodes at a nesting depth.

    Args:
        depth: Zero-based depth of the nodes being generated.

    Returns:
        A strategy yielding one group (leaf, block or repeat).

    Raises:
        None.
    """
    if depth >= MAX_DEPTH:
        return _leaves
    child = _groups(st.deferred(lambda: _group_at_depth(depth + 1)))
    return st.one_of(_leaves, _blocks(child), _repeats(child), _orientations())


def trees() -> st.SearchStrategy[list[GenNode]]:
    """Generate top-level node lists.

    Returns:
        A strategy of lists of ``GenNode`` up to ``MAX_DEPTH`` levels deep.

    Raises:
        None.
    """
    return _groups(_group_at_depth(0))


@st.composite
def _indent_style(draw: st.DrawFn) -> IndentStyle:
    """Draw an indentation style with strictly increasing widths.

    Args:
        draw: Hypothesis draw function.

    Returns:
        An ``IndentStyle`` of tabs, spaces or a mix.

    Raises:
        None.
    """
    step = st.text(alphabet="\t ", min_size=1, max_size=4)
    prefixes = [""]
    for _ in range(MAX_DEPTH):
        prefixes.append(prefixes[-1] + draw(step))
    return IndentStyle(tuple(prefixes))


indent_style: st.SearchStrategy[IndentStyle] = _indent_style()
"""Strategy of ``IndentStyle`` (tabs, spaces or mixed, strictly increasing)."""

separators: st.SearchStrategy[str] = st.sampled_from(["\t", " ", "  ", "\t\t", " \t"])
"""Strategy of key/value separators (runs of tabs and spaces)."""

headers: st.SearchStrategy[str] = st.sampled_from(["TXT", "TXT2"])
"""Strategy of file headers."""


# -------------------------------------------------------------- rendering


def render_tree(
    nodes: list[GenNode],
    header: str = "TXT",
    separator: str = "\t",
    indent: IndentStyle = TAB_INDENT,
    newline: str = "\n",
) -> str:
    """Render a generated tree as file text.

    Args:
        nodes: Top-level nodes.
        header: ``"TXT"`` or ``"TXT2"`` (written on the first line).
        separator: Text between a key and its value.
        indent: Indentation prefix per depth.
        newline: Line terminator.

    Returns:
        The file text, ending with a line terminator.

    Raises:
        IndexError: If the tree is deeper than ``MAX_DEPTH``.
    """
    lines = [header]

    def walk(group: list[GenNode], depth: int) -> None:
        for n in group:
            line = indent.for_depth(depth) + n.key
            if n.value is not None:
                line += ("" if not n.key else separator) + _format_value(n.value)
            lines.append(line)
            walk(n.children, depth + 1)

    walk(nodes, 0)
    return newline.join(lines) + newline


def matches_parsed(expected: list[GenNode], actual: list[Node]) -> bool:
    """Compare a generated tree with parser nodes (keys, values, children).

    Args:
        expected: Generated nodes.
        actual: Parsed nodes at the same level.

    Returns:
        True when both trees have the same shape, keys and values.

    Raises:
        None.
    """
    if len(expected) != len(actual):
        return False
    return all(
        e.key == a.key and e.value == a.value and matches_parsed(e.children, a.children)
        for e, a in zip(expected, actual, strict=True)
    )


__all__ = [
    "MAX_DEPTH",
    "TAB_INDENT",
    "GenNode",
    "IndentStyle",
    "headers",
    "indent_style",
    "matches_parsed",
    "render_tree",
    "separators",
    "trees",
]
