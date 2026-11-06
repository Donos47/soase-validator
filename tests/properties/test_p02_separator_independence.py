"""Property test for key/value separator independence.

# Feature: soase-validator, Property 2: Separator independence

For any parsed tree, replacing each key/value separator with any non-empty
run of tabs and spaces yields the same parsed tree.

The ``key = "value"`` form is out of scope here: it is a fixed shape (``=``
surrounded by whitespace, quoted value), not a separator, and is covered by
unit tests in ``tests/test_parser_facts.py``.

**Validates: Requirements 2.2**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.trees import (
    GenNode,
    headers,
    matches_parsed,
    render_tree,
    trees,
)

from soase_validator.engine.parser import Node, parse

_runs = st.text(alphabet="\t ", min_size=1, max_size=6)


def _project(nodes: list[Node]) -> list[tuple[str, Any, list[Any]]]:
    """Project parsed nodes onto key, value and children.

    Args:
        nodes: Parsed nodes.

    Returns:
        Nested tuples ignoring positions.

    Raises:
        None.
    """
    return [(n.key, n.value, _project(n.children)) for n in nodes]


@settings(max_examples=100, deadline=None)
@given(tree=trees(), header=headers, sep_a=_runs, sep_b=_runs)
def test_separator_independence(tree: list[GenNode], header: str, sep_a: str, sep_b: str) -> None:
    """Different separator runs parse to the same tree.

    Args:
        tree: Generated tree.
        header: File header.
        sep_a: First separator run.
        sep_b: Second separator run.

    Returns:
        None.

    Raises:
        AssertionError: If the parsed trees differ.
    """
    base = parse(render_tree(tree, header=header, separator="\t"))
    a = parse(render_tree(tree, header=header, separator=sep_a))
    b = parse(render_tree(tree, header=header, separator=sep_b))

    assert matches_parsed(tree, a.nodes)
    assert matches_parsed(tree, b.nodes)
    assert _project(a.nodes) == _project(base.nodes) == _project(b.nodes)
    assert a.header == base.header == b.header
