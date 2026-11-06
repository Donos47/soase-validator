"""Property test: recorded spans match the source text."""

# Feature: soase-validator, Property 3: Recorded spans match source
# For any parsed file and any node, the source text at the node's key span
# equals the key, and the text at its value span equals the value's source form.

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.trees import (
    GenNode,
    IndentStyle,
    headers,
    indent_style,
    render_tree,
    separators,
    trees,
)

from soase_validator.engine.model import Span
from soase_validator.engine.parser import Node, _format_value, parse


def _slice(lines: list[str], span: Span) -> str:
    """Return the source text covered by a single-line span.

    Args:
        lines: Source lines without terminators.
        span: Zero-based span on one line.

    Returns:
        The text between the span's start and exclusive end column.

    Raises:
        AssertionError: If the span covers more than one line.
    """
    assert span.line == span.end_line
    return lines[span.line][span.col : span.end_col]


def _walk(nodes: list[Node]) -> list[Node]:
    """Flatten a node tree in document order.

    Args:
        nodes: Sibling nodes.

    Returns:
        All nodes, parents before children.

    Raises:
        None.
    """
    out: list[Node] = []
    for n in nodes:
        out.append(n)
        out.extend(_walk(n.children))
    return out


@settings(max_examples=100)
@given(
    tree=trees(),
    header=headers,
    separator=separators,
    style=indent_style,
    newline=st.sampled_from(["\n", "\r\n"]),
)
def test_recorded_spans_match_source(
    tree: list[GenNode],
    header: str,
    separator: str,
    style: IndentStyle,
    newline: str,
) -> None:
    """Key and value spans of every node slice back to the source text.

    **Validates: Requirements 2.6**

    Args:
        tree: Generated tree.
        header: File header.
        separator: Key/value separator.
        style: Indentation style.
        newline: Line terminator.

    Returns:
        None.

    Raises:
        AssertionError: If any span disagrees with the source.
    """
    text = render_tree(tree, header, separator, style, newline)
    lines = text.split("\n")
    lines = [ln.rstrip("\r") for ln in lines]
    parsed = parse(text)

    for node in _walk(parsed.nodes):
        assert _slice(lines, node.key_span) == node.key
        if node.value is None:
            assert node.value_span is None
        else:
            assert node.value_span is not None
            assert _slice(lines, node.value_span) == _format_value(node.value)
