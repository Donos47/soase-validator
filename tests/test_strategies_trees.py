"""Sanity checks for the tree and indentation strategies."""

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

from soase_validator.engine.parser import parse


@settings(max_examples=100)
@given(nodes=trees(), header=headers, sep=separators, indent=indent_style)
def test_rendered_trees_parse_back(
    nodes: list[GenNode], header: str, sep: str, indent: IndentStyle
) -> None:
    """Rendered text parses without diagnostics into the generated tree."""
    parsed = parse(render_tree(nodes, header, sep, indent))
    assert parsed.diagnostics == []
    assert parsed.header == header
    assert matches_parsed(nodes, parsed.nodes)


@settings(max_examples=100)
@given(style=indent_style)
def test_indent_widths_strictly_increase(style: IndentStyle) -> None:
    """Each depth's indentation is strictly wider than the previous one."""
    widths = [len(p) for p in style.prefixes]
    assert widths[0] == 0
    assert all(a < b for a, b in zip(widths, widths[1:], strict=False))
