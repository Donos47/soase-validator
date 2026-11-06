"""Property test for structural diagnostics.

# Feature: soase-validator, Property 11: Structural diagnostics

For any structure and generated file that omits a required field, includes a
key not defined for the active version, or declares an iterative count that
differs from its block count or exceeds its limit, validation reports an
error of the matching kind on the expected location, and reports none of
these for a file generated without those faults.

Codes and locations, as emitted by ``engine/validator.py``:

* ``SOASE-V040`` required field missing, on the key of the enclosing block,
  or on the header line (line 0) for the file root (Requirement 3.5);
* ``SOASE-V020`` key not defined for the active Game Version, on the key;
* ``SOASE-V030`` count differs from the number of repeats, or exceeds the
  ``limit``, on the count line (a count that is both wrong and over the
  limit yields both).

Synthetic Definitions only; no game files.

**Validates: Requirements 3.5, 3.6, 3.7**
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.definitions import VERSION_GATES

from soase_validator.engine.diagnostics import V020, V030, V040
from soase_validator.engine.model import Diagnostic, Severity
from soase_validator.engine.parser import parse
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import GameVersion, gate_allows

_VERSIONS = st.sampled_from(list(GameVersion))
_GATES = st.none() | st.sampled_from(VERSION_GATES)
_PATH = Path("a.foo")
_HEADER = "TXT"

Where = tuple[str, int, int, int, int]


def _where(diag: Diagnostic) -> Where:
    """Return ``(code, line, col, end line, end col)`` of a Diagnostic."""
    r = diag.range
    return (diag.code, r.start.line, r.start.col, r.end.line, r.end.col)


def _run(files: dict[str, str], text: str, version: GameVersion) -> list[Diagnostic]:
    """Parse ``text`` as a ``.foo`` file and validate it at ``version``."""
    registry = load_registry_from_texts(files)
    assert registry.warnings == ()
    return validate(parse(text, _PATH), ValidationContext(registry, version, _PATH))


@st.composite
def _cases(draw: st.DrawFn):
    """Draw a root structure, a Game Version and a file with chosen faults.

    Returns:
        ``(files, version, text, expected)`` where ``expected`` is the sorted
        list of ``(code, line, col, end line, end col)`` the validator must
        report, computed from the draw alone.
    """
    version = draw(_VERSIONS)
    fields = draw(
        st.lists(
            st.tuples(st.booleans(), _GATES),
            min_size=1,
            max_size=6,
        )
    )
    limit = draw(st.none() | st.integers(0, 4))
    iter_gate = draw(_GATES)
    iter_required = draw(st.booleans())

    children: list[dict] = [
        {"node": "field", "name": f"f{i}", "validation": "Any", "required": req, "version": gate}
        for i, (req, gate) in enumerate(fields)
    ]
    iterative: dict = {
        "node": "iterative_field",
        "name": "w",
        "count_key": "wCount",
        "validation": "Any",
        "required": iter_required,
    }
    if limit is not None:
        iterative["limit"] = limit
    if iter_gate is not None:
        iterative["version"] = iter_gate
    children.append(iterative)
    root = {"name": "Root", "extension": ".foo", "children": children}
    files = {"s.json": json.dumps({"structures": [root]})}

    lines: list[str] = [_HEADER]
    expected: list[Where] = []

    for i, (req, gate) in enumerate(fields):
        allowed = gate_allows(gate, version)
        present = draw(st.booleans())
        if present:
            lines.append(f"f{i} 1")
            if not allowed:
                expected.append((V020, len(lines) - 1, 0, len(lines) - 1, 1 + len(str(i))))
        elif allowed and req:
            expected.append((V040, 0, 0, 0, len(_HEADER)))

    iter_allowed = gate_allows(iter_gate, version)
    has_count = draw(st.booleans())
    if has_count:
        count = draw(st.integers(0, 6))
        repeats = draw(st.integers(0, 6))
        lines.append(f"wCount {count}")
        count_line = len(lines) - 1
        width = len(lines[-1])
        lines.extend("w 1" for _ in range(repeats))
        if not iter_allowed:
            # Neither the count line nor its repeats are defined for the version;
            expected.append((V020, count_line, 0, count_line, len("wCount")))
            expected.extend(
                (V020, count_line + 1 + k, 0, count_line + 1 + k, 1) for k in range(repeats)
            )
        else:
            if limit is not None and count > limit:
                expected.append((V030, count_line, 0, count_line, width))
            if count != repeats:
                expected.append((V030, count_line, 0, count_line, width))
    elif iter_allowed and iter_required:
        expected.append((V040, 0, 0, 0, len(_HEADER)))

    return files, version, "\n".join(lines) + "\n", sorted(expected)


@settings(max_examples=100)
@given(case=_cases())
def test_structural_faults_are_reported_where_expected(case) -> None:
    """Missing required, undefined and miscounted entries are reported exactly."""
    files, version, text, expected = case
    diags = _run(files, text, version)
    assert all(d.severity is Severity.ERROR for d in diags)
    assert sorted(_where(d) for d in diags) == expected


@settings(max_examples=100)
@given(
    version=_VERSIONS,
    fields=st.lists(st.tuples(st.booleans(), _GATES), min_size=1, max_size=6),
    limit=st.none() | st.integers(0, 4),
    data=st.data(),
)
def test_file_without_faults_reports_no_structural_diagnostics(
    version: GameVersion, fields, limit, data
) -> None:
    """Every required allowed field present, nothing undefined, count right: no report."""
    children = [
        {"node": "field", "name": f"f{i}", "validation": "Any", "required": req, "version": gate}
        for i, (req, gate) in enumerate(fields)
    ]
    iterative: dict = {
        "node": "iterative_field",
        "name": "w",
        "count_key": "wCount",
        "validation": "Any",
        "required": True,
    }
    if limit is not None:
        iterative["limit"] = limit
    children.append(iterative)
    files = {
        "s.json": json.dumps(
            {"structures": [{"name": "Root", "extension": ".foo", "children": children}]}
        )
    }
    lines = [_HEADER]
    for i, (req, gate) in enumerate(fields):
        if gate_allows(gate, version) and (req or data.draw(st.booleans())):
            lines.append(f"f{i} 1")
    n = data.draw(st.integers(0, 4 if limit is None else limit))
    lines.append(f"wCount {n}")
    lines.extend("w 1" for _ in range(n))
    assert _run(files, "\n".join(lines) + "\n", version) == []


def _nested_files() -> dict[str, str]:
    """Root ``.foo`` structure with a required block ``blk`` holding a required ``x``."""
    root = {
        "name": "Root",
        "extension": ".foo",
        "children": [{"node": "structure_reference", "name": "blk", "structure": "Inner"}],
    }
    inner = {
        "name": "Inner",
        "children": [{"node": "field", "name": "x", "validation": "Any", "required": True}],
    }
    return {"s.json": json.dumps({"structures": [root, inner]})}


def test_missing_required_in_block_is_reported_on_the_block_key() -> None:
    """V040 for a nested block sits on the block's key, not the header."""
    diags = _run(_nested_files(), "TXT\nblk\n", GameVersion.REBELLION_198)
    assert [_where(d) for d in diags] == [(V040, 1, 0, 1, 3)]


def test_nested_block_with_required_field_is_clean() -> None:
    """The same block with its required field present reports nothing."""
    assert _run(_nested_files(), "TXT\nblk\n\tx 1\n", GameVersion.REBELLION_198) == []


def test_unknown_key_is_reported_on_the_key() -> None:
    """V020 spans the key of a key the structure does not define."""
    diags = _run(_nested_files(), "TXT\nblk\n\tx 1\nzz 2\n", GameVersion.REBELLION_198)
    assert [_where(d) for d in diags] == [(V020, 3, 0, 3, 2)]
