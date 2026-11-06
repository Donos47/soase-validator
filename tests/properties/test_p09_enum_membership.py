"""Property test for version-gated enumeration membership.

# Feature: soase-validator, Property 9: Enumeration membership is version-gated

For any enumeration, Game Version and candidate value, validation accepts the
value if and only if it is a member whose gate allows that Game Version. The
enumeration's own gate is part of that rule (Requirement 3.9). A value that
fails is reported as ``SOASE-V050`` on the value (Requirement 3.4); an
``entityType`` that is unknown for the version is reported as ``SOASE-V010``
on the value (Requirement 3.2).

Synthetic Definitions only; no game files.

**Validates: Requirements 3.2, 3.4, 3.9**
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.definitions import VERSION_GATES, enum_to_json

from soase_validator.engine.diagnostics import V010, V050
from soase_validator.engine.model import Diagnostic, Severity
from soase_validator.engine.parser import parse
from soase_validator.engine.registry import EnumDef, EnumValueDef, load_registry_from_texts
from soase_validator.engine.validator import ValidationContext, validate
from soase_validator.engine.versions import GameVersion, gate_allows

_VERSIONS = st.sampled_from(list(GameVersion))
_GATES = st.none() | st.sampled_from(VERSION_GATES)
_NAMES = st.text(alphabet="abcdefghij0123456789_", min_size=1, max_size=6).map(lambda s: "M" + s)


@st.composite
def _enums(draw: st.DrawFn, name: str) -> EnumDef:
    """Draw an enumeration with gated members and an optional enum gate."""
    names = draw(st.lists(_NAMES, min_size=1, max_size=6, unique=True))
    members = tuple(EnumValueDef(n, draw(_GATES)) for n in names)
    return EnumDef(name=name, values=members, version=draw(_GATES))


def _expected(enum: EnumDef, text: str, version: GameVersion) -> bool:
    """Oracle: the value is a member whose gate (and the enum's) allows the version."""
    if not gate_allows(enum.version, version):
        return False
    return any(m.name == text and gate_allows(m.version, version) for m in enum.values)


def _validate(registry_files: dict[str, str], name: str, body: str, version: GameVersion):
    """Parse a ``TXT`` file and validate it at ``version``."""
    registry = load_registry_from_texts(registry_files)
    assert registry.warnings == ()
    path = Path(name)
    return validate(parse(f"TXT\n{body}", path), ValidationContext(registry, version, path))


def _field_files(enum: EnumDef) -> dict[str, str]:
    """Definitions with a root structure whose field ``k`` is bound to ``enum``."""
    root = {
        "name": "Root",
        "extension": ".foo",
        "children": [{"node": "field", "name": "k", "type": enum.name}],
    }
    return {
        "s.json": json.dumps({"structures": [root]}),
        "enums.json": json.dumps({"enums": [enum_to_json(enum)]}),
    }


def _only(diags: list[Diagnostic], code: str, body_line: str, text: str) -> None:
    """Assert exactly one error ``code`` sits on the quoted value ``text``."""
    assert [d.code for d in diags] == [code]
    (diag,) = diags
    assert diag.severity is Severity.ERROR
    start = body_line.index(f'"{text}"')
    assert diag.range.start.line == 1
    assert diag.range.start.col == start
    assert diag.range.end.col == start + len(text) + 2


@settings(max_examples=100)
@given(enum=_enums("kind"), version=_VERSIONS, data=st.data())
def test_member_accepted_iff_gate_allows(enum: EnumDef, version: GameVersion, data) -> None:
    """A member is accepted exactly when it and its enumeration allow the version."""
    member = data.draw(st.sampled_from([m.name for m in enum.values]))
    line = f'k "{member}"'
    diags = _validate(_field_files(enum), "a.foo", line + "\n", version)
    if _expected(enum, member, version):
        assert diags == []
    else:
        _only(diags, V050, line, member)


@settings(max_examples=100)
@given(enum=_enums("kind"), version=_VERSIONS, other=_NAMES)
def test_non_member_is_rejected(enum: EnumDef, version: GameVersion, other: str) -> None:
    """A value that is not a member is an error on every version."""
    if other in {m.name for m in enum.values}:
        other += "_x"
    line = f'k "{other}"'
    diags = _validate(_field_files(enum), "a.foo", line + "\n", version)
    _only(diags, V050, line, other)


@settings(max_examples=100)
@given(enum=_enums("entityType"), version=_VERSIONS, data=st.data(), unknown=st.booleans())
def test_entity_type_known_iff_member_allows_version(
    enum: EnumDef, version: GameVersion, data, unknown: bool
) -> None:
    """``entityType`` is known exactly when it is a member that allows the version."""
    text = "Unlisted" if unknown else data.draw(st.sampled_from([m.name for m in enum.values]))
    structures = [{"name": m.name, "children": []} for m in enum.values]
    files = {
        "s.json": json.dumps({"structures": structures}),
        "enums.json": json.dumps({"enums": [enum_to_json(enum)]}),
    }
    line = f'entityType "{text}"'
    diags = _validate(files, "x.entity", line + "\n", version)
    if _expected(enum, text, version):
        assert diags == []
    else:
        _only(diags, V010, line, text)
