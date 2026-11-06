"""Unit tests for the structural and value validator (Requirement 3).

Definitions and files are synthetic. The shapes mirror the Rebellion 1.98
reference files (shapes and counts only; no game content): particle
``NumEmitters`` followed by ``EmitterType`` + ``EmitterContents`` sibling
sequences, ``.str`` ``NumStrings`` + ``StringInfo`` blocks, ``.galaxy``
``useRandomGenerator`` with a Boolean selector, count-prefixed repeated
value lines (``SoundID``) and unquoted ``TRUE``/``FALSE`` enumeration values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.model import Diagnostic
from soase_validator.engine.parser import parse
from soase_validator.engine.primitives import NumericPrefs
from soase_validator.engine.registry import Registry, load_registry, load_registry_from_texts
from soase_validator.engine.validator import (
    Found,
    NotFound,
    NullReferenceLookup,
    ResolveResult,
    Unknown,
    ValidationContext,
    definition_warnings,
    validate,
)
from soase_validator.engine.versions import GameVersion


def _registry(
    children: list[dict[str, Any]],
    *,
    extra: list[dict[str, Any]] | None = None,
    enums: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> Registry:
    """Build a Registry whose root structure ``Root`` has extension ``.foo``."""
    structures = [{"name": "Root", "extension": ".foo", "children": children}, *(extra or [])]
    files = {"s.json": json.dumps({"structures": structures, "element_rules": rules or []})}
    if enums is not None:
        files["enums.json"] = json.dumps({"enums": enums})
    registry = load_registry_from_texts(files)
    assert registry.warnings == ()
    return registry


def _run(
    registry: Registry,
    body: str,
    *,
    header: str = "TXT",
    name: str = "a.foo",
    version: GameVersion = GameVersion.REBELLION_198,
    numeric: NumericPrefs | None = None,
    lookup: Any = None,
) -> list[Diagnostic]:
    """Parse ``body`` (tab-indented lines) and validate it."""
    path = Path(name)
    parsed = parse(f"{header}\n{body}", path)
    ctx = ValidationContext(
        registry,
        version,
        path,
        numeric or NumericPrefs(),
        lookup or NullReferenceLookup(),
    )
    return validate(parsed, ctx)


def _brief(diags: list[Diagnostic]) -> list[tuple[str, int, int, int]]:
    """Reduce Diagnostics to (code, line, col, end col) on one line."""
    return [(d.code, d.range.start.line, d.range.start.col, d.range.end.col) for d in diags]


def _f(name: str, validation: str | None = None, **extra: Any) -> dict[str, Any]:
    """A field node."""
    node: dict[str, Any] = {"node": "field", "name": name, **extra}
    if validation:
        node["validation"] = validation
    return node


class _Lookup:
    """Lookup returning a fixed result and recording the calls."""

    def __init__(self, result: ResolveResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def resolve(self, kind: str, name: str) -> ResolveResult:
        self.calls.append((kind, name))
        return self.result


# ---- extension, header keys, file stamping --------------------------------


def test_extension_without_definition_is_ignored() -> None:
    registry = _registry([_f("a", "Integer")])
    assert _run(registry, "zzz 1\n", name="a.unknown") == []


def test_diagnostics_carry_file_and_zero_based_spans() -> None:
    registry = _registry([_f("a", "Integer")])
    (diag,) = _run(registry, "\tb 1\n")  # indented key is a child of nothing: top level
    assert diag.file == Path("a.foo")
    assert diag.code == dg.V020 and diag.severity.value == "error"
    # Line 0 is the header; the key `b` sits on line 1 after one unit of indent.
    assert (diag.range.start.line, diag.range.start.col, diag.range.end.col) == (1, 1, 2)


def test_txt2_archive_version_is_a_header_key_but_txt_is_not() -> None:
    registry = _registry([_f("a", "Integer")])
    assert _run(registry, "SinsArchiveVersion 194\na 1\n", header="TXT2") == []
    codes = _brief(_run(registry, "SinsArchiveVersion 194\na 1\n", header="TXT"))
    assert codes == [(dg.V020, 1, 0, len("SinsArchiveVersion"))]


def test_no_output_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    registry = _registry([_f("a", "Integer")])
    _run(registry, "a x\n")
    assert capsys.readouterr().out == ""


# ---- 3.1 / 3.2 entity root --------------------------------------------------

_ENTITY_ENUM = [
    {"name": "entityType", "values": ["Frigate", {"name": "Titan", "version": "Rebellion"}]}
]
_ENTITY_STRUCTS = [
    {"name": "Frigate", "children": [_f("speed", "Decimal", required=True)]},
    {"name": "Titan", "children": [_f("mass", "Decimal")]},
]


def _entity_registry() -> Registry:
    return _registry([], extra=_ENTITY_STRUCTS, enums=_ENTITY_ENUM)


def test_entity_type_selects_structure() -> None:
    registry = _entity_registry()
    body = 'SinsArchiveVersion 194\nentityType "Frigate"\nspeed 1.500000\n'
    assert _run(registry, body, header="TXT2", name="x.entity") == []
    # `mass` belongs to Titan only: the structure really comes from entityType.
    bad = 'SinsArchiveVersion 194\nentityType "Frigate"\nspeed 1.0\nmass 2.0\n'
    codes = _brief(_run(registry, bad, header="TXT2", name="x.entity"))
    assert codes == [(dg.V020, 4, 0, 4)]


def test_unknown_entity_type_reported_on_value() -> None:
    registry = _entity_registry()
    diags = _run(registry, 'entityType "Nope"\n', header="TXT2", name="x.entity")
    assert _brief(diags) == [(dg.V010, 1, len("entityType "), len('entityType "Nope"'))]


def test_entity_type_is_version_gated() -> None:
    registry = _entity_registry()
    body = 'entityType "Titan"\nmass 1.0\n'
    assert _run(registry, body, header="TXT2", name="x.entity") == []
    diags = _run(registry, body, header="TXT2", name="x.entity", version=GameVersion.DIPLOMACY)
    assert [d.code for d in diags] == [dg.V010]


def test_missing_entity_type_is_a_required_field_error() -> None:
    registry = _entity_registry()
    diags = _run(registry, "speed 1.0\n", header="TXT2", name="x.entity")
    assert _brief(diags) == [(dg.V040, 0, 0, len("TXT2"))]


# ---- 3.3 primitives, constraint, Orientation -------------------------------


@pytest.mark.parametrize(
    ("validation", "good", "bad"),
    [
        ("Boolean", "TRUE", "yes"),
        ("Integer", "-3", '"3"'),
        ("Decimal", "1.500000", "1e3"),
        ("Color", "ff00ff00", '"ff00ff00"'),
        ("Position", "[ 1 , 2 ]", "[ 1.5 , 2 ]"),
        ("Coordinate", "[ 0.100000 0.200000 0.300000 ]", "[ 0.1 0.2 ]"),
    ],
)
def test_primitive_values_are_checked(validation: str, good: str, bad: str) -> None:
    registry = _registry([_f("v", validation)])
    assert _run(registry, f"v {good}\n") == []
    diags = _run(registry, f"v {bad}\n")
    # `yes` is an unparseable line (parser P002), so it never reaches the validator.
    expected = [] if bad == "yes" else [dg.V050]
    assert [d.code for d in diags] == expected
    if expected:
        assert diags[0].range.start.col == 2  # on the value, not the key
        assert diags[0].message.startswith("v: ")


def test_any_accepts_a_key_without_value() -> None:
    registry = _registry([_f("v", "Any")])
    assert _run(registry, "v\n") == []


def test_missing_value_for_typed_field_is_invalid() -> None:
    registry = _registry([_f("v", "Integer")])
    assert _brief(_run(registry, "v\n")) == [(dg.V050, 1, 0, 1)]


def test_block_where_value_expected_is_invalid() -> None:
    registry = _registry([_f("v", "Integer")])
    diags = _run(registry, "v\n\tx 1\n")
    assert [d.code for d in diags] == [dg.V050]


def test_position_constraint_is_passed_to_the_checker() -> None:
    registry = _registry([_f("pos", "Position", constraint="count=2")])
    assert _run(registry, "pos [ 1 , 2 ]\n") == []
    assert [d.code for d in _run(registry, "pos [ 1 , 2 , 3 ]\n")] == [dg.V050]
    assert [d.code for d in _run(registry, "pos [ 1 ]\n")] == [dg.V050]


def test_malformed_constraint_is_a_load_warning_and_never_raises() -> None:
    registry = _registry(
        [
            _f("pos", "Position", constraint="count=x"),
            _f("n", "Integer", constraint="count=2"),
        ]
    )
    warnings = definition_warnings(registry)
    assert [(w.file, w.element, w.code) for w in warnings] == [
        ("s.json", "Root.pos", dg.D001),
        ("s.json", "Root.n", dg.D001),
    ]
    assert "count=x" in warnings[0].message and "Integer" in warnings[1].message
    # Validation still runs: the shape is checked and the bad count is ignored.
    assert _run(registry, "pos [ 1 , 2 , 3 ]\nn 1\n") == []
    assert [d.code for d in _run(registry, "pos [ 1.5 , 2 ]\n")] == [dg.V050]


def test_bundled_definitions_have_no_constraint_warnings() -> None:
    assert definition_warnings(load_registry()) == ()


def test_orientation_takes_the_header_node() -> None:
    registry = _registry([_f("Orientation", "Orientation")])
    rows = "\t[ 1.000000 0.000000 0.000000 ]\n" * 3
    assert _run(registry, f"Orientation\n{rows}") == []
    two_rows = "\t[ 1.000000 0.000000 0.000000 ]\n" * 2
    diags = _run(registry, f"Orientation\n{two_rows}")
    assert _brief(diags) == [(dg.V050, 1, 0, len("Orientation"))]
    bad_row = "\t[ 1.0 0.0 ]\n" + rows.splitlines(keepends=True)[0] * 2
    assert [d.code for d in _run(registry, f"Orientation\n{bad_row}")] == [dg.V050]


def test_element_rule_supplies_the_validation_of_an_untyped_field() -> None:
    registry = _registry([_f("isShared")], rules=[{"name": "isShared", "validation": "Boolean"}])
    assert _run(registry, "isShared TRUE\n") == []
    assert [d.code for d in _run(registry, "isShared 5\n")] == [dg.V050]


# ---- 3.10 numeric preferences ----------------------------------------------


def test_numeric_preferences_are_applied() -> None:
    registry = _registry([_f("i", "Integer"), _f("d", "Decimal")])
    body = "i 1.500000\nd 5\n"
    assert _run(registry, body) == []
    strict = NumericPrefs(integer_strict=True, decimal_allow_integer=False)
    diags = _run(registry, body, numeric=strict)
    assert _brief(diags) == [(dg.V050, 1, 2, 10), (dg.V050, 2, 2, 3)]


# ---- 3.4 enumerations, 3.9 gates -------------------------------------------

_KIND_ENUM = [
    {
        "name": "kind",
        "values": [
            "A",
            {"name": "B", "version": "Rebellion194"},
            "TRUE",
            "7",
        ],
    }
]


def test_enum_membership_and_written_form() -> None:
    registry = _registry([{"node": "field", "name": "k", "type": "kind"}], enums=_KIND_ENUM)
    assert _run(registry, 'k "A"\n') == []
    assert _run(registry, "k TRUE\n") == []  # unquoted boolean member
    assert _run(registry, "k 7\n") == [] and _run(registry, 'k "7"\n') == []
    for bad in ('k "Z"', 'k "TRUE"', "k FALSE", "k 8"):
        assert [d.code for d in _run(registry, f"{bad}\n")] == [dg.V050], bad


def test_enum_member_is_version_gated() -> None:
    registry = _registry([{"node": "field", "name": "k", "type": "kind"}], enums=_KIND_ENUM)
    assert _run(registry, 'k "B"\n') == []
    diags = _run(registry, 'k "B"\n', version=GameVersion.REBELLION_185)
    assert _brief(diags) == [(dg.V050, 1, 2, 5)]


def test_inline_values_are_enumeration_members() -> None:
    registry = _registry([_f("k", "Simple", values=["Credits", "Metal"])])
    assert _run(registry, 'k "Metal"\n') == []
    assert [d.code for d in _run(registry, 'k "Gold"\n')] == [dg.V050]


def test_field_and_structure_gates_define_keys() -> None:
    registry = _registry(
        [
            _f("old", "Integer"),
            _f("new", "Integer", version="Rebellion194", required=True),
            {"node": "structure_reference", "name": "blk", "structure": "Gated"},
        ],
        extra=[{"name": "Gated", "version": "Rebellion194", "children": []}],
    )
    ok = _run(registry, "old 1\nnew 2\nblk\n")
    assert ok == []
    v185 = _run(registry, "old 1\nnew 2\nblk\n", version=GameVersion.REBELLION_185)
    assert _brief(v185) == [(dg.V020, 2, 0, 3), (dg.V020, 3, 0, 3)]
    # A gated-out required field is not required (and not reported missing).
    assert _run(registry, "old 1\n", version=GameVersion.REBELLION_185) == []
    assert [d.code for d in _run(registry, "old 1\n")] == [dg.V040]


# ---- 3.5 required, 3.6 unknown ---------------------------------------------


def test_required_field_missing_is_reported_on_the_file_header() -> None:
    registry = _registry([_f("a", "Integer", required=True)])
    assert _brief(_run(registry, "")) == [(dg.V040, 0, 0, len("TXT"))]
    assert _run(registry, "a 1\n") == []


def test_required_field_missing_in_a_block_is_reported_on_the_block_key() -> None:
    registry = _registry(
        [{"node": "structure_reference", "name": "blk", "structure": "Inner"}],
        extra=[{"name": "Inner", "children": [_f("x", "Integer", required=True), _f("z")]}],
    )
    diags = _run(registry, "blk\n\tz 1\n")
    assert _brief(diags) == [(dg.V040, 1, 0, 3)]
    assert "'x'" in diags[0].message and "Inner" in diags[0].message


def test_required_applies_to_each_repeated_block() -> None:
    registry = _registry(
        [
            {
                "node": "iterative_field",
                "name": "star",
                "count_key": "starCount",
                "children": [_f("n", "Integer", required=True)],
            }
        ]
    )
    diags = _run(registry, "starCount 2\nstar\n\tn 1\nstar\n\tm 1\n")
    assert [(d.code, d.range.start.line) for d in diags] == [
        (dg.V020, 5),
        (dg.V040, 4),
    ]


def test_unknown_key_in_nested_block_is_reported_on_the_key() -> None:
    registry = _registry(
        [{"node": "structure_reference", "name": "blk", "structure": "Inner"}],
        extra=[{"name": "Inner", "children": [_f("x", "Integer")]}],
    )
    assert _brief(_run(registry, "blk\n\tx 1\n\tq 2\n")) == [(dg.V020, 3, 1, 2)]
    # Key match is exact: a different case is a different key.
    assert [d.code for d in _run(registry, "blk\n\tX 1\n")] == [dg.V020]


def test_keyless_row_outside_orientation_is_unexpected() -> None:
    registry = _registry([_f("a", "Integer")])
    diags = _run(registry, "[ 1.0 2.0 3.0 ]\n")
    assert [d.code for d in diags] == [dg.V020]


def test_skipped_parser_line_leaves_a_required_field_missing() -> None:
    # The doubled closing quote makes the parser skip the line (P002); the
    # validator then sees no `Value` node and reports it missing.
    registry = _registry(
        [
            {
                "node": "iterative_field",
                "name": "StringInfo",
                "count_key": "NumStrings",
                "children": [_f("ID", "Any"), _f("Value", "Any", required=True)],
            }
        ]
    )
    text = 'NumStrings 1\nStringInfo\n\tID "a"\n\tValue "b""\n'
    parsed = parse(f"TXT\n{text}", Path("a.foo"))
    assert [d.code for d in parsed.diagnostics] == [dg.P002]
    diags = validate(parsed, ValidationContext(registry, GameVersion.REBELLION_198, Path("a.foo")))
    assert _brief(diags) == [(dg.V040, 2, 0, len("StringInfo"))]


def test_indentation_decides_which_block_a_line_belongs_to() -> None:
    # Real galaxy files indent a planet's `owner` one level less than the rest
    # of the planet. Block extent comes from indentation alone, so the line
    # belongs to the star (the parent) and is reported there.
    registry = _registry(
        [{"node": "structure_reference", "name": "star", "structure": "Star"}],
        extra=[
            {
                "name": "Star",
                "children": [
                    _f("planetCount", "Integer"),
                    {"node": "structure_reference", "name": "planet", "structure": "Planet"},
                ],
            },
            {"name": "Planet", "children": [_f("designName", "Any"), _f("owner", "Any")]},
        ],
    )
    body = 'star\n\tplanetCount 1\n\tplanet\n\t\tdesignName "p"\n\towner "P0"\n'
    diags = _run(registry, body)
    assert _brief(diags) == [(dg.V020, 5, 1, 6)]


# ---- 3.7 iterative fields --------------------------------------------------

_STARS = [
    {
        "node": "iterative_field",
        "name": "star",
        "count_key": "starCount",
        "limit": 3,
        "children": [_f("n", "Integer")],
    }
]
_LINE = len("starCount 2")


def test_block_repeats_match_their_count() -> None:
    registry = _registry(_STARS)
    assert _run(registry, "starCount 2\nstar\n\tn 1\nstar\n\tn 2\n") == []
    assert _run(registry, "starCount 0\n") == []


def test_too_few_and_too_many_blocks_are_reported_on_the_count_line() -> None:
    registry = _registry(_STARS)
    few = _run(registry, "starCount 2\nstar\n\tn 1\n")
    assert _brief(few) == [(dg.V030, 1, 0, _LINE)]
    assert "2" in few[0].message and "1" in few[0].message
    many = _run(registry, "starCount 1\nstar\n\tn 1\nstar\n\tn 2\n")
    assert _brief(many) == [(dg.V030, 1, 0, _LINE)]


def test_count_over_limit_is_reported_even_when_blocks_match() -> None:
    registry = _registry(_STARS)
    body = "starCount 4\n" + "star\n\tn 1\n" * 4
    diags = _run(registry, body)
    assert _brief(diags) == [(dg.V030, 1, 0, _LINE)]
    assert "limit" in diags[0].message


def test_non_integer_count_is_an_invalid_value() -> None:
    registry = _registry(_STARS)
    assert [d.code for d in _run(registry, "starCount 1.5\nstar\n\tn 1\n")] == [dg.V050]
    assert [d.code for d in _run(registry, "starCount -1\n")] == [dg.V050]


def test_repeat_without_count_line_is_reported() -> None:
    registry = _registry(_STARS)
    diags = _run(registry, "star\n\tn 1\n")
    assert _brief(diags) == [(dg.V030, 1, 0, 4)]
    assert "starCount" in diags[0].message


def test_repeated_value_lines_follow_their_own_count_line() -> None:
    # Five iterative fields in each entity structure share the repeat key
    # `SoundID`; only the count line before the run tells them apart.
    registry = _registry(
        [
            {"node": "iterative_field", "name": "SoundID", "count_key": "onA", "validation": "Any"},
            {"node": "iterative_field", "name": "SoundID", "count_key": "onB", "validation": "Any"},
        ]
    )
    assert _run(registry, 'onA 1\nSoundID "x"\nonB 2\nSoundID "y"\nSoundID "z"\n') == []
    diags = _run(registry, 'onA 1\nSoundID "x"\nonB 1\nSoundID "y"\nSoundID "z"\n')
    assert _brief(diags) == [(dg.V030, 3, 0, len("onB 1"))]


def test_repeated_value_lines_are_checked_by_validation() -> None:
    registry = _registry(
        [{"node": "iterative_field", "name": "w", "count_key": "wCount", "validation": "Integer"}]
    )
    assert [d.code for d in _run(registry, 'wCount 1\nw "x"\n')] == [dg.V050]


_EMITTERS = [
    {
        "node": "iterative_field",
        "name": "EmitterType",
        "count_key": "NumEmitters",
        "limit": 2,
        "children": [
            {
                "node": "condition_field",
                "name": "EmitterType",
                "type": "EType",
                "branches": {
                    "Point": [
                        {"node": "structure_reference", "name": "EmitterContents",
                         "structure": "Pt", "required": True}
                    ],
                    "Ring": [
                        {"node": "structure_reference", "name": "EmitterContents",
                         "structure": "Rg", "required": True}
                    ],
                },
            }
        ],
    }
]  # fmt: skip
_EMITTER_EXTRA = [
    {"name": "Pt", "children": [_f("w", "Integer", required=True)]},
    {"name": "Rg", "children": [_f("r", "Decimal")]},
]
_EMITTER_ENUM = [{"name": "EType", "values": ["Point", "Ring", "Sphere"]}]
_TWO = 'EmitterType "Point"\nEmitterContents\n\tw 1\nEmitterType "Ring"\nEmitterContents\n\tr 1.5\n'


def _emitters() -> Registry:
    return _registry(_EMITTERS, extra=_EMITTER_EXTRA, enums=_EMITTER_ENUM)


def test_sibling_sequences_match_their_count() -> None:
    assert _run(_emitters(), f"NumEmitters 2\n{_TWO}") == []
    assert _run(_emitters(), "NumEmitters 0\n") == []


def test_sibling_sequences_too_few_too_many_and_over_limit() -> None:
    registry = _emitters()
    one = 'EmitterType "Point"\nEmitterContents\n\tw 1\n'
    few = _run(registry, f"NumEmitters 2\n{one}")
    assert _brief(few) == [(dg.V030, 1, 0, len("NumEmitters 2"))]
    many = _run(registry, f"NumEmitters 1\n{_TWO}")
    assert _brief(many) == [(dg.V030, 1, 0, len("NumEmitters 1"))]
    third = 'EmitterType "Point"\nEmitterContents\n\tw 1\n'
    over = _run(registry, f"NumEmitters 3\n{_TWO}{third}")
    assert [(d.code, "limit" in d.message) for d in over] == [(dg.V030, True)]


def test_sibling_sequence_uses_the_branch_of_its_own_selector() -> None:
    # `w` belongs to the Point contents only; the Ring sequence rejects it.
    body = 'NumEmitters 1\nEmitterType "Ring"\nEmitterContents\n\tw 1\n'
    diags = _run(_emitters(), body)
    assert _brief(diags) == [(dg.V020, 4, 1, 2)]


def test_sibling_sequence_missing_its_block_is_a_missing_required_field() -> None:
    diags = _run(_emitters(), 'NumEmitters 1\nEmitterType "Point"\n')
    assert _brief(diags) == [(dg.V040, 2, 0, len("EmitterType"))]
    assert "EmitterContents" in diags[0].message


def test_sibling_sequence_block_without_selector_is_unknown() -> None:
    diags = _run(_emitters(), "NumEmitters 0\nEmitterContents\n\tw 1\n")
    assert [d.code for d in diags] == [dg.V020]


def test_sibling_sequence_selector_value_is_checked() -> None:
    diags = _run(_emitters(), 'NumEmitters 1\nEmitterType "Cube"\n')
    assert dg.V050 in [d.code for d in diags]


# ---- 3.8 condition branches ------------------------------------------------


def _branches() -> Registry:
    return _registry(
        [
            {
                "node": "condition_field",
                "name": "kind",
                "type": "K",
                "branches": {
                    "A": [_f("a", "Integer", required=True)],
                    "B": [_f("b", "Integer")],
                },
            },
            {
                "node": "condition_field",
                "name": "flag",
                "validation": "Boolean",
                "branches": {"TRUE": [_f("t", "Integer")], "FALSE": [_f("f", "Integer")]},
            },
        ],
        enums=[{"name": "K", "values": ["A", "B", "C"]}],
    )


def test_selected_branch_keys_are_accepted() -> None:
    registry = _branches()
    assert _run(registry, 'kind "A"\na 1\n') == []
    assert _run(registry, 'kind "B"\nb 1\n') == []
    assert _run(registry, 'kind "C"\n') == []  # a member with no branch keys


def test_keys_of_other_branches_are_undefined() -> None:
    registry = _branches()
    diags = _run(registry, 'kind "A"\na 1\nb 2\n')
    assert _brief(diags) == [(dg.V020, 3, 0, 1)]
    assert "kind is B" in diags[0].message
    assert [d.code for d in _run(registry, 'kind "B"\na 1\n')] == [dg.V020]


def test_required_field_of_a_branch_applies_only_when_selected() -> None:
    registry = _branches()
    assert [d.code for d in _run(registry, 'kind "A"\n')] == [dg.V040]
    assert _run(registry, 'kind "B"\n') == []


def test_boolean_selector_chooses_its_branch() -> None:
    registry = _branches()
    assert _run(registry, "flag TRUE\nt 1\n") == []
    assert [d.code for d in _run(registry, "flag TRUE\nf 1\n")] == [dg.V020]
    assert [d.code for d in _run(registry, "flag FALSE\nf 1\n")] == []


# ---- 4.x references ---------------------------------------------------------


def _refs() -> Registry:
    return _registry([_f("b", "Brush"), _f("t", "Texture"), _f("e", "Entity")])


def test_unresolved_reference_names_kind_and_value() -> None:
    lookup = _Lookup(NotFound())
    diags = _run(_refs(), 'b "Missing"\n', lookup=lookup)
    assert _brief(diags) == [(dg.R010, 1, 2, len('b "Missing"'))]
    assert "Brush" in diags[0].message and "Missing" in diags[0].message
    assert lookup.calls == [("Brush", "Missing")]


@pytest.mark.parametrize("result", [Found(), Unknown()])
def test_found_and_unknown_references_report_nothing(result: ResolveResult) -> None:
    assert _run(_refs(), 'b "X"\ne "Y"\n', lookup=_Lookup(result)) == []


def test_default_lookup_reports_nothing() -> None:
    assert _run(_refs(), 'b "X"\n') == []


def test_empty_names_and_texture_names_are_not_resolved() -> None:
    lookup = _Lookup(NotFound())
    assert _run(_refs(), 'b ""\nt "Anything"\n', lookup=lookup) == []
    assert lookup.calls == []


def test_reference_value_must_be_a_quoted_name() -> None:
    assert [d.code for d in _run(_refs(), "b 5\n")] == [dg.V050]
    assert [d.code for d in _run(_refs(), "t 5\n")] == [dg.V050]


# ---- nested structures and block shapes ------------------------------------


def test_structure_reference_value_where_block_expected() -> None:
    registry = _registry(
        [{"node": "structure_reference", "name": "blk", "structure": "Inner"}],
        extra=[{"name": "Inner", "children": []}],
    )
    assert [d.code for d in _run(registry, "blk 1\n")] == [dg.V050]


def test_condition_reference_picks_structure_from_sibling_selector() -> None:
    registry = _registry(
        [
            _f("t", "Any"),
            {
                "node": "condition_reference",
                "name": "blk",
                "selector": "t",
                "cases": {"x": "SX"},
            },
        ],
        extra=[{"name": "SX", "children": [_f("p", "Integer")]}],
    )
    assert _run(registry, 't "x"\nblk\n\tp 1\n') == []
    assert [d.code for d in _run(registry, 't "x"\nblk\n\tq 1\n')] == [dg.V020]
    assert [d.code for d in _run(registry, 't "y"\nblk\n\tp 1\n')] == [dg.V020]


# ---- real-shaped bundled Definitions ---------------------------------------


def test_particle_sequences_validate_with_bundled_definitions() -> None:
    registry = load_registry()
    body = (
        "ParticleSimulation\n"
        "\tHasInfiniteLifeTime FALSE\n"
        "\tTotalLifeTime 10.000000\n"
        "\tNumEmitters 0\n"
        "\tNumAffectors 0\n"
        "\tlength 1.000000\n"
    )
    assert _run(registry, body, header="TXT2", name="x.particle") == []
    wrong = body.replace("NumEmitters 0", "NumEmitters 1")
    diags = _run(registry, wrong, header="TXT2", name="x.particle")
    assert [d.code for d in diags] == [dg.V030]


# ---- Reference Root (skipped without game files) ---------------------------


def test_reference_root_particle_and_simple_files_validate_clean(reference_root: Path) -> None:
    registry = load_registry()
    checked = 0
    for pattern in ("*.particle", "*.brushes", "*.sounddata", "*.str", "*.explosiondata"):
        for path in sorted(reference_root.rglob(pattern)):
            parsed = parse(path.read_text(encoding="utf-8-sig", errors="replace"), path)
            ctx = ValidationContext(registry, GameVersion.REBELLION_198, path)
            assert validate(parsed, ctx) == [], path.name
            checked += 1
    assert checked > 0


def test_reference_root_has_no_order_or_duplicate_findings(reference_root: Path) -> None:
    # Survey of the Rebellion 1.98 files (3066 text files): no key breaks the
    # declared order and one `.entity` file repeats `buffType` in an Ability.
    # The two galaxy files with the known indentation artefact are excluded.
    registry = load_registry()
    artefacts = {"Voruk's Labyrinth.galaxy", "Hyperion's Gates.galaxy"}
    found: list[tuple[str, str]] = []
    for path in sorted(reference_root.rglob("*")):
        if not path.is_file() or path.name in artefacts:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if not text.startswith("TXT"):
            continue
        ctx = ValidationContext(registry, GameVersion.REBELLION_198, path)
        for diag in validate(parse(text, path), ctx):
            if diag.code in (dg.V060, dg.V070):
                found.append((diag.code, path.name))
    assert found == [(dg.V070, "AbilityShieldProjection.entity")]


# ---- declared order (V060) and duplicates (V070) ---------------------------


def _ordered() -> Registry:
    return _registry(
        [_f("a", "Integer"), _f("b", "Integer"), _f("c", "Integer"), _f("d", "Integer")]
    )


def test_keys_in_declared_order_pass_and_optional_keys_may_be_absent() -> None:
    registry = _ordered()
    assert _run(registry, "a 1\nb 2\nc 3\nd 4\n") == []
    assert _run(registry, "a 1\nd 4\n") == []
    assert _run(registry, "") == []


def test_one_misplaced_key_gives_exactly_one_v060_and_no_cascade() -> None:
    registry = _ordered()
    # `a` last: the three keys after the start are still in order.
    diags = _run(registry, "b 2\nc 3\nd 4\na 1\n")
    assert _brief(diags) == [(dg.V060, 4, 0, 1)]
    assert "'a'" in diags[0].message and "before 'b'" in diags[0].message
    # `d` first: reported once, told to come after `c`.
    diags = _run(registry, "d 4\na 1\nb 2\nc 3\n")
    assert _brief(diags) == [(dg.V060, 1, 0, 1)]
    assert "after 'c'" in diags[0].message
    # A swapped pair is one report, not two.
    assert len(_run(registry, "a 1\nc 3\nb 2\nd 4\n")) == 1


def test_duplicate_plain_key_gives_one_v070_and_no_v060() -> None:
    registry = _ordered()
    diags = _run(registry, "a 1\nb 2\na 3\nc 4\n")
    assert _brief(diags) == [(dg.V070, 3, 0, 1)]
    assert "line 2" in diags[0].message  # first use: file line 2 (header is line 1)
    # Adjacent duplicates are duplicates too.
    assert [d.code for d in _run(registry, "a 1\na 1\n")] == [dg.V070]


def test_unknown_key_is_not_reported_as_out_of_order() -> None:
    registry = _ordered()
    assert [d.code for d in _run(registry, "a 1\nzzz 1\nb 2\n")] == [dg.V020]
    assert [d.code for d in _run(registry, "b 1\nzzz 1\na 2\n")] == [dg.V020, dg.V060]


def test_gated_out_field_does_not_count_for_order() -> None:
    registry = _registry(
        [_f("a", "Integer"), _f("old", "Integer", version="Rebellion194"), _f("b", "Integer")]
    )
    assert _run(registry, "a 1\nold 2\nb 3\n") == []
    # In 185 `old` is undefined (V020) and a/b keep their order.
    diags = _run(registry, "a 1\nold 2\nb 3\n", version=GameVersion.REBELLION_185)
    assert [d.code for d in diags] == [dg.V020]


def test_condition_branch_sits_right_after_its_selector() -> None:
    registry = _registry(
        [
            _f("first", "Integer"),
            {
                "node": "condition_field",
                "name": "kind",
                "type": "K",
                "branches": {"A": [_f("x", "Integer"), _f("y", "Integer")]},
            },
            _f("last", "Integer"),
        ],
        enums=[{"name": "K", "values": ["A", "B"]}],
    )
    assert _run(registry, 'first 1\nkind "A"\nx 1\ny 2\nlast 3\n') == []
    assert _run(registry, 'first 1\nkind "B"\nlast 3\n') == []
    # Branch keys after `last`, or before the selector, are out of order.
    assert [d.code for d in _run(registry, 'first 1\nkind "A"\nx 1\nlast 3\ny 2\n')] == [dg.V060]
    assert [d.code for d in _run(registry, 'first 1\nx 1\nkind "A"\ny 2\nlast 3\n')] == [dg.V060]


def test_iterative_run_occupies_the_position_of_its_field() -> None:
    registry = _registry(
        [
            _f("a", "Integer"),
            *_STARS,
            _f("z", "Integer"),
        ]
    )
    assert _run(registry, "a 1\nstarCount 2\nstar\n\tn 1\nstar\n\tn 2\nz 3\n") == []
    # The whole run counts once: `a` after it is one report.
    body = "starCount 2\nstar\n\tn 1\nstar\n\tn 2\nz 3\na 1\n"
    diags = _run(registry, body)
    assert _brief(diags) == [(dg.V060, 7, 0, 1)]


def test_counted_repeats_are_not_duplicates() -> None:
    registry = _registry(_STARS)
    assert _run(registry, "starCount 3\n" + "star\n\tn 1\n" * 3) == []
    # A second count line is a duplicate of the first.
    diags = _run(registry, "starCount 1\nstar\n\tn 1\nstarCount 1\nstar\n\tn 1\n")
    assert [d.code for d in diags] == [dg.V070]


def test_iterative_fields_sharing_a_repeat_key_are_not_duplicates() -> None:
    registry = _registry(
        [
            {"node": "iterative_field", "name": "SoundID", "count_key": "onA", "validation": "Any"},
            {"node": "iterative_field", "name": "SoundID", "count_key": "onB", "validation": "Any"},
        ]
    )
    assert _run(registry, 'onA 1\nSoundID "x"\nonB 2\nSoundID "y"\nSoundID "z"\n') == []
    # Declared order still applies to the two count lines.
    diags = _run(registry, 'onB 1\nSoundID "y"\nonA 1\nSoundID "x"\n')
    assert [d.code for d in diags] == [dg.V060]


def test_sibling_sequences_are_ordered_by_selector_then_branch_then_rest() -> None:
    registry = _emitters()
    assert _run(registry, f"NumEmitters 2\n{_TWO}") == []
    swapped = 'NumEmitters 1\nEmitterContents\n\tw 1\nEmitterType "Point"\n'
    # The block precedes its selector: unknown at the block level, no V060 cascade.
    assert dg.V060 not in [d.code for d in _run(registry, swapped)]


def test_bundled_particle_order_is_enforced() -> None:
    body = (
        "ParticleSimulation\n"
        "\tHasInfiniteLifeTime FALSE\n"
        "\tTotalLifeTime 10.000000\n"
        "\tlength 1.000000\n"
        "\tNumEmitters 0\n"
        "\tNumAffectors 0\n"
    )
    diags = _run(load_registry(), body, header="TXT2", name="x.particle")
    assert [d.code for d in diags] == [dg.V060]
    assert "'length'" in diags[0].message


def test_nested_blocks_are_ordered_independently() -> None:
    registry = _registry(
        [{"node": "structure_reference", "name": "blk", "structure": "Inner"}],
        extra=[{"name": "Inner", "children": [_f("x", "Integer"), _f("y", "Integer")]}],
    )
    assert _run(registry, "blk\n\tx 1\n\ty 2\n") == []
    assert _brief(_run(registry, "blk\n\ty 2\n\tx 1\n")) == [(dg.V060, 2, 1, 2)]
    assert "Inner" in _run(registry, "blk\n\ty 2\n\tx 1\n")[0].message


def test_resolve_protocol_types_are_distinct() -> None:
    assert Found() != NotFound() != Unknown()
    assert isinstance(NullReferenceLookup().resolve("Brush", "x"), Unknown)
