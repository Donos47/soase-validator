"""Property test for missing file headers.

# Feature: soase-validator, Property 5: Missing header

For any file body whose first non-empty line is neither ``TXT`` nor ``TXT2``,
parsing reports an error Diagnostic at line 1 (``SOASE-P001``) and the
remaining content still parses.

**Validates: Requirements 2.7**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.trees import GenNode, matches_parsed, render_tree, trees

from soase_validator.engine.model import Severity
from soase_validator.engine.parser import parse

_NOT_HEADERS = frozenset({"TXT", "TXT2"})

_first_lines = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters='"[]'),
    min_size=1,
    max_size=10,
).filter(lambda s: s not in _NOT_HEADERS)


@settings(max_examples=100, deadline=None)
@given(tree=trees(), first_line=_first_lines)
def test_missing_header_reports_p001_and_keeps_parsing(
    tree: list[GenNode], first_line: str
) -> None:
    """A non-header first line yields P001 at line 0 and the body still parses.

    Args:
        tree: Generated body tree.
        first_line: A first line that is neither ``TXT`` nor ``TXT2``.

    Returns:
        None.

    Raises:
        AssertionError: If the diagnostic is missing or the body is not parsed.
    """
    parsed = parse(render_tree(tree, header=first_line))

    assert parsed.header is None
    p001 = [d for d in parsed.diagnostics if d.code == "SOASE-P001"]
    assert len(p001) == 1
    assert p001[0].severity is Severity.ERROR
    assert p001[0].range.start.line == 0

    # The remaining content still parses: the body nodes follow the first line.
    body = parsed.nodes[-len(tree) :] if tree else []
    assert matches_parsed(tree, body)


def test_missing_header_on_empty_file() -> None:
    """An empty file reports P001 at line 0 without raising.

    Returns:
        None.

    Raises:
        AssertionError: If P001 is not reported.
    """
    parsed = parse("")
    assert [d.code for d in parsed.diagnostics] == ["SOASE-P001"]
    assert parsed.diagnostics[0].range.start.line == 0
