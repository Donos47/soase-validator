"""Property test for parser recovery.

# Feature: soase-validator, Property 4: Parser recovery

For any valid file and any single line replaced with unparseable text, the
parser reports at least one Diagnostic and still returns every node from
lines before and after the corrupted line unchanged.

**Validates: Requirements 2.8**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.trees import GenNode, headers, render_tree, separators, trees

from soase_validator.engine.diagnostics import Diagnostic
from soase_validator.engine.parser import Node, StringValue, Value, parse

_GARBAGE = ["@@@", "12xyz", "[1, x]", "[1,2", "TRUEISH", "1.2.3", "{}", "-", "[1] 2"]
_UNQUOTED = st.text(alphabet="abc def!?", max_size=8)


def _flat_expected(nodes: list[GenNode]) -> list[tuple[str, Value | None]]:
    """Flatten generated nodes in file line order.

    Args:
        nodes: Generated nodes.

    Returns:
        ``(key, value)`` pairs in pre-order, matching rendered line order.

    Raises:
        None.
    """
    out: list[tuple[str, Value | None]] = []
    for n in nodes:
        out.append((n.key, n.value))
        out.extend(_flat_expected(n.children))
    return out


def _flat_parsed(nodes: list[Node]) -> list[tuple[str, Value | None]]:
    """Flatten parsed nodes in line order.

    Args:
        nodes: Parsed nodes.

    Returns:
        ``(key, value)`` pairs in pre-order.

    Raises:
        None.
    """
    out: list[tuple[str, Value | None]] = []
    for n in nodes:
        out.append((n.key, n.value))
        out.extend(_flat_parsed(n.children))
    return out


def _codes(diags: list[Diagnostic]) -> set[str]:
    """Return the set of diagnostic codes.

    Args:
        diags: Diagnostics.

    Returns:
        The codes present.

    Raises:
        None.
    """
    return {d.code for d in diags}


def test_every_garbage_text_is_unparseable_on_its_own() -> None:
    """No garbage text is a valid value (hex token, number, list, bool, string).

    Guards the generator: the parser accepts bare hex tokens such as ``beef``,
    the ``key = "v"`` form and keyless ``[`` rows, so each text used to corrupt
    a line must still be rejected after ``Broken<sep>``.
    """
    for garbage in _GARBAGE:
        for sep in ("\t", " "):
            result = parse(f"TXT\nBroken{sep}{garbage}\n")
            assert [d.code for d in result.diagnostics] == ["SOASE-P002"], garbage
            assert result.nodes == [], garbage


@settings(max_examples=100)
@given(
    nodes=trees().filter(bool),
    header=headers,
    sep=separators,
    data=st.data(),
)
def test_unparseable_line_is_skipped_and_neighbours_survive(
    nodes: list[GenNode], header: str, sep: str, data: st.DataObject
) -> None:
    """A garbage line is reported (P002) and every other node is returned."""
    flat = _flat_expected(nodes)
    idx = data.draw(st.integers(0, len(flat) - 1))
    garbage = data.draw(st.sampled_from(_GARBAGE))
    lines = render_tree(nodes, header, sep).split("\n")
    line_no = idx + 1  # header occupies line 0
    indent = lines[line_no][: len(lines[line_no]) - len(lines[line_no].lstrip("\t"))]
    lines[line_no] = f"{indent}Broken{sep}{garbage}"

    result = parse("\n".join(lines))

    assert "SOASE-P002" in _codes(result.diagnostics)
    assert _flat_parsed(result.nodes) == flat[:idx] + flat[idx + 1 :]


@settings(max_examples=100)
@given(
    nodes=trees().filter(bool),
    header=headers,
    sep=separators,
    tail=_UNQUOTED,
    data=st.data(),
)
def test_unterminated_quote_is_recovered_and_neighbours_survive(
    nodes: list[GenNode], header: str, sep: str, tail: str, data: st.DataObject
) -> None:
    """An unterminated quote is reported (P003) and all other nodes survive."""
    flat = _flat_expected(nodes)
    idx = data.draw(st.integers(0, len(flat) - 1))
    lines = render_tree(nodes, header, sep).split("\n")
    line_no = idx + 1
    indent = lines[line_no][: len(lines[line_no]) - len(lines[line_no].lstrip("\t"))]
    lines[line_no] = f'{indent}Broken{sep}"{tail}'

    result = parse("\n".join(lines))

    assert "SOASE-P003" in _codes(result.diagnostics)
    got = _flat_parsed(result.nodes)
    assert len(got) == len(flat)
    assert got[idx] == ("Broken", StringValue(tail.rstrip(), terminated=False))
    assert got[:idx] == flat[:idx]
    assert got[idx + 1 :] == flat[idx + 1 :]


@settings(max_examples=100)
@given(
    nodes=trees().filter(bool),
    header=headers,
    sep=separators,
    garbage=st.lists(st.sampled_from(_GARBAGE), min_size=1, max_size=3),
    data=st.data(),
)
def test_inserted_garbage_lines_never_raise_and_keep_all_nodes(
    nodes: list[GenNode],
    header: str,
    sep: str,
    garbage: list[str],
    data: st.DataObject,
) -> None:
    """Inserting garbage lines reports Diagnostics and keeps every valid node."""
    flat = _flat_expected(nodes)
    lines = render_tree(nodes, header, sep).split("\n")
    for g in garbage:
        pos = data.draw(st.integers(1, len(lines) - 1))
        lines.insert(pos, f"Junk{sep}{g}")

    result = parse("\n".join(lines))

    assert "SOASE-P002" in _codes(result.diagnostics)
    assert _flat_parsed(result.nodes) == flat
