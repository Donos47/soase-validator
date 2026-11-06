"""Property test for the parse round trip.

# Feature: soase-validator, Property 1: Parse round trip

For any valid tree and either header, parsing the rendered text and then
parsing the formatted result yields an equivalent tree with no Diagnostics.

**Validates: Requirements 2.1, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

from hypothesis import given, settings
from tests.strategies.trees import (
    GenNode,
    IndentStyle,
    headers,
    indent_style,
    matches_parsed,
    render_tree,
    separators,
    trees,
)

from soase_validator.engine.parser import Node, format_tree, parse


def _same_tree(a: list[Node], b: list[Node]) -> bool:
    """Compare two parsed trees by key, value and children only.

    Args:
        a: First node list.
        b: Second node list.

    Returns:
        True when the trees are equivalent, ignoring spans and indentation.

    Raises:
        None.
    """
    return len(a) == len(b) and all(
        x.key == y.key and x.value == y.value and _same_tree(x.children, y.children)
        for x, y in zip(a, b, strict=True)
    )


@settings(max_examples=100)
@given(nodes=trees(), header=headers, sep=separators, indent=indent_style)
def test_parse_format_parse_round_trip(
    nodes: list[GenNode], header: str, sep: str, indent: IndentStyle
) -> None:
    """parse(format_tree(parse(text))) equals the tree, with no Diagnostics."""
    first = parse(render_tree(nodes, header, sep, indent))
    assert first.diagnostics == []
    assert first.header == header
    assert matches_parsed(nodes, first.nodes)

    second = parse(format_tree(first))
    assert second.diagnostics == []
    assert second.header == header
    assert _same_tree(first.nodes, second.nodes)
    assert matches_parsed(nodes, second.nodes)
