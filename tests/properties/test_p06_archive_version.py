"""Property test for SinsArchiveVersion handling.

# Feature: soase-validator, Property 6: Archive version handling

For any ``TXT`` file, no missing-``SinsArchiveVersion`` Diagnostic is produced.
For any ``TXT2`` file with a non-integer ``SinsArchiveVersion`` value, an error
is produced, and for any integer not recognised for the active Game Version,
only an informational Diagnostic is produced.

**Validates: Requirements 2.10, 2.11**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.trees import GenNode, render_tree, trees

from soase_validator.engine.model import Severity
from soase_validator.engine.parser import parse

_versions = st.integers(-1_000_000, 1_000_000)
_known_sets = st.frozensets(st.integers(0, 400), max_size=6)

_non_integers = st.one_of(
    st.integers(-1000, 1000).map(lambda n: f"{n}.5"),
    st.sampled_from(["TRUE", "FALSE", "1e3", '"194"', "abc", "[ 1 , 2 ]", ""]),
)


def _with_version(tree: list[GenNode], header: str, value_text: str | None) -> str:
    """Render a tree with an optional ``SinsArchiveVersion`` line after the header.

    Args:
        tree: Generated body tree.
        header: File header.
        value_text: Raw version value text, or None to omit the line.

    Returns:
        The file text.

    Raises:
        None.
    """
    lines = render_tree(tree, header=header).split("\n")
    if value_text is not None:
        lines.insert(1, f"SinsArchiveVersion\t{value_text}".rstrip())
    return "\n".join(lines)


def _version_diags(text: str, known: frozenset[int] | None) -> list:
    """Parse text and return the P004 Diagnostics.

    Args:
        text: File text.
        known: Known archive versions, or None.

    Returns:
        The ``SOASE-P004`` Diagnostics.

    Raises:
        None.
    """
    parsed = parse(text, known_archive_versions=known)
    return [d for d in parsed.diagnostics if d.code == "SOASE-P004"]


@settings(max_examples=100, deadline=None)
@given(
    tree=trees(),
    value=st.one_of(st.none(), _versions.map(str), _non_integers),
    known=st.one_of(st.none(), _known_sets),
)
def test_txt_files_never_get_version_diagnostics(
    tree: list[GenNode], value: str | None, known: frozenset[int] | None
) -> None:
    """A TXT file never gets a missing or invalid version Diagnostic.

    Args:
        tree: Generated body tree.
        value: Version value text, or None to omit the line.
        known: Known archive versions, or None.

    Returns:
        None.

    Raises:
        AssertionError: If any P004 is produced.
    """
    assert _version_diags(_with_version(tree, "TXT", value), known) == []


@settings(max_examples=100, deadline=None)
@given(tree=trees(), value=_non_integers, known=st.one_of(st.none(), _known_sets))
def test_txt2_non_integer_version_is_error(
    tree: list[GenNode], value: str, known: frozenset[int] | None
) -> None:
    """A non-integer version in a TXT2 file gives a P004 error.

    Args:
        tree: Generated body tree.
        value: Non-integer version value text.
        known: Known archive versions, or None.

    Returns:
        None.

    Raises:
        AssertionError: If no error P004 is produced.
    """
    parsed = parse(_with_version(tree, "TXT2", value), known_archive_versions=known)
    # Values that parse (decimals, booleans, strings, lists, no value) give P004;
    # unparseable text is rejected by the tolerant parser with P002 instead.
    on_line = [d for d in parsed.diagnostics if d.range.start.line == 1]
    assert on_line
    assert all(d.severity is Severity.ERROR for d in on_line)
    assert {d.code for d in on_line} <= {"SOASE-P002", "SOASE-P004"}


@settings(max_examples=100, deadline=None)
@given(tree=trees(), version=_versions, known=_known_sets)
def test_txt2_integer_version_known_or_unknown(
    tree: list[GenNode], version: int, known: frozenset[int]
) -> None:
    """An unknown integer gives one informational P004; a known one gives none.

    Args:
        tree: Generated body tree.
        version: Integer version.
        known: Known archive versions.

    Returns:
        None.

    Raises:
        AssertionError: If the Diagnostics do not match the expectation.
    """
    diags = _version_diags(_with_version(tree, "TXT2", str(version)), known)
    if version in known:
        assert diags == []
    else:
        assert len(diags) == 1
        assert diags[0].severity is Severity.INFO
        # No error-level Diagnostic arises from the version line itself.
        assert all(d.severity is not Severity.ERROR for d in diags)


@settings(max_examples=100, deadline=None)
@given(tree=trees(), version=_versions)
def test_txt2_integer_version_without_known_set_is_silent(
    tree: list[GenNode], version: int
) -> None:
    """With no known set the recognition check is skipped.

    Args:
        tree: Generated body tree.
        version: Integer version.

    Returns:
        None.

    Raises:
        AssertionError: If any P004 is produced.
    """
    assert _version_diags(_with_version(tree, "TXT2", str(version)), None) == []
