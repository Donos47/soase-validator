"""Property test for indentation style independence.

# Feature: soase-validator, Property 37: Indentation style independence

For any valid tree and any re-indentation of it using tabs, spaces or a mix of
both, provided indentation widths increase strictly with nesting depth,
parsing the re-indented text produces the same tree as parsing the tab-indented
text, and no indentation-related Diagnostic is produced.

**Validates: Requirements 2.3, 2.4**
"""

from __future__ import annotations

from hypothesis import given, settings
from tests.strategies.trees import (
    TAB_INDENT,
    GenNode,
    IndentStyle,
    headers,
    indent_style,
    matches_parsed,
    render_tree,
    separators,
    trees,
)

from soase_validator.engine.parser import Node, parse


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
def test_indentation_style_does_not_change_tree(
    nodes: list[GenNode], header: str, sep: str, indent: IndentStyle
) -> None:
    """Any strictly increasing indent style parses like tabs, with no Diagnostics."""
    baseline = parse(render_tree(nodes, header, sep, TAB_INDENT))
    restyled = parse(render_tree(nodes, header, sep, indent))

    assert baseline.diagnostics == []
    assert restyled.diagnostics == []
    assert _same_tree(baseline.nodes, restyled.nodes)
    assert matches_parsed(nodes, restyled.nodes)
