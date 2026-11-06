"""Unit tests for tools/convert_definitions.py using small synthetic XML."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from soase_validator.engine.registry import (
    ConditionFieldDef,
    FieldDef,
    IterativeFieldDef,
    load_registry,
)

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "convert_definitions.py"
_spec = importlib.util.spec_from_file_location("convert_definitions", _TOOL)
assert _spec is not None and _spec.loader is not None
conv = importlib.util.module_from_spec(_spec)
sys.modules["convert_definitions"] = conv
_spec.loader.exec_module(conv)

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<tns:entity_definitions xmlns:tns="http://www.example.org/element_definitions/">\n'
)
FOOTER = "</tns:entity_definitions>\n"


def _xml(body: str) -> str:
    return HEADER + body + FOOTER


def _structure(result, file: str, name: str) -> dict:
    for entry in result.files[file]["structures"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"{name} not found in {file}")


def test_fields_attributes_and_help() -> None:
    xml = _xml(
        '<structure name="Galaxy" help="About">'
        '<field name="a" validation="Integer" required="true" version="Rebellion" help="h"/>'
        '<field name="b" validation="Simple" values="X, Y"/>'
        "</structure>"
    )
    result = conv.convert_texts({"galaxy.xml": xml})
    struct = _structure(result, "galaxy.json", "Galaxy")
    assert struct["extension"] == ".galaxy"
    assert struct["help"] == "About"
    a, b = struct["children"]
    assert a == {
        "node": "field",
        "name": "a",
        "required": True,
        "version": "Rebellion",
        "help": "h",
        "validation": "Integer",
    }
    assert b["values"] == ["X", "Y"]
    assert result.report.unconverted == []


def test_gated_inline_values_become_enum() -> None:
    xml = _xml(
        '<structure name="S"><field name="f" validation="Simple">'
        '<value>One</value><value version="Rebellion">Two</value></field></structure>'
    )
    result = conv.convert_texts({"s.xml": xml})
    field_node = _structure(result, "s.json", "S")["children"][0]
    enum_name = field_node["type"]
    enums = {e["name"]: e for e in result.files["enums.json"]["enums"]}
    assert enums[enum_name]["values"] == ["One", {"name": "Two", "version": "Rebellion"}]


def test_nested_structure_is_hoisted_and_referenced() -> None:
    xml = _xml(
        '<structure name="P"><structure name="inner" version="Diplomacy">'
        '<field name="x" validation="Decimal"/></structure>'
        '<structure_reference name="r" type="Other"/></structure>'
        '<structure name="Other"/>'
    )
    result = conv.convert_texts({"p.xml": xml})
    p = _structure(result, "p.json", "P")
    assert p["children"][0] == {
        "node": "structure_reference",
        "name": "inner",
        "structure": "P.inner",
        "version": "Diplomacy",
    }
    assert p["children"][1]["structure"] == "Other"
    assert _structure(result, "p.json", "P.inner")["children"][0]["name"] == "x"


def test_iterative_field_variants() -> None:
    xml = _xml(
        '<structure name="Str"><iterative_field name="NumStrings" limit="5">'
        '<structure_reference name="StringInfo" type="StringInfo"/></iterative_field>'
        '<iterative_field name="idCount"><field name="id" validation="Entity"/></iterative_field>'
        "</structure>"
        '<structure name="StringInfo"><field name="ID" validation="Any"/></structure>'
    )
    result = conv.convert_texts({"string_info.xml": xml})
    children = _structure(result, "string_info.json", "Str")["children"]
    block, plain = children
    assert (block["name"], block["count_key"], block["limit"]) == ("StringInfo", "NumStrings", 5)
    assert block["children"][0]["name"] == "ID"
    assert (plain["name"], plain["count_key"], plain["validation"]) == ("id", "idCount", "Entity")


def test_inline_condition_field_branches_and_boolean_selector() -> None:
    xml = _xml(
        '<structure name="S"><condition_field name="flag">'
        '<condition value="TRUE"><field name="a" validation="Integer"/></condition>'
        '<condition value="FALSE"/></condition_field></structure>'
    )
    result = conv.convert_texts({"s.xml": xml})
    node = _structure(result, "s.json", "S")["children"][0]
    assert node["validation"] == "Boolean"
    assert list(node["branches"]) == ["TRUE", "FALSE"]
    assert node["branches"]["TRUE"][0]["name"] == "a"
    assert node["branches"]["FALSE"] == []


def test_top_level_condition_is_enum_and_expanded_at_use_site() -> None:
    cond = _xml(
        '<condition_field name="kind"><condition>'
        '<value version="Rebellion">A</value><value>B</value>'
        '<field name="extra" validation="Decimal"/></condition></condition_field>'
    )
    user = _xml('<structure name="U"><field name="kind" type="kind" required="true"/></structure>')
    result = conv.convert_texts({"kind.xml": cond, "u.xml": user})
    node = _structure(result, "u.json", "U")["children"][0]
    assert node["node"] == "condition_field"
    assert node["type"] == "kind"
    assert node["required"] is True
    assert set(node["branches"]) == {"A", "B"}
    enums = {e["name"]: e for e in result.files["enums.json"]["enums"]}
    assert enums["kind"]["values"] == [{"name": "A", "version": "Rebellion"}, "B"]
    assert "kind.json" not in result.files


def test_element_rule_becomes_enum_and_typed_field() -> None:
    rules = _xml(
        '<element_rule name="role" validation="Simple">'
        '<value>Light</value><value version="Rebellion">Heavy</value></element_rule>'
    )
    user = _xml('<structure name="U"><field name="role"/></structure>')
    result = conv.convert_texts({"common.xml": rules, "u.xml": user})
    rule = result.files["common.json"]["element_rules"][0]
    assert rule == {"name": "role", "validation": "Simple", "type": "role"}
    assert _structure(result, "u.json", "U")["children"][0]["type"] == "role"


def test_problems_are_reported_not_raised() -> None:
    result = conv.convert_texts(
        {
            "bad.xml": "<not-closed",
            "plugin.xml": "<plugin/>",
            "x.xml": _xml(
                '<structure name="S"><field validation="Integer"/>'
                '<field name="f" referenceType="y"/>'
                '<structure_reference name="r" type="Missing"/></structure>'
            ),
        }
    )
    text = "\n".join(result.report.unconverted)
    assert "malformed XML" in text
    assert "element without a name" in text
    assert "attribute 'referenceType'" in text
    assert "unknown structure 'Missing'" in text
    assert result.report.skipped_files == ["plugin.xml"]


def test_written_output_loads_in_registry_without_warnings(tmp_path: Path) -> None:
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "a.xml").write_text(
        _xml(
            '<structure name="Brushes"><iterative_field name="n">'
            '<structure_reference name="b" type="B"/></iterative_field>'
            '<condition_field name="t"><condition value="X"><field name="f" validation="Integer"/>'
            "</condition></condition_field></structure>"
            '<structure name="B"><field name="k" validation="Any"/></structure>'
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code = conv.main([str(xml_dir), "--output", str(out), "--strict"])
    assert code == 0
    assert json.loads((out / "enums.json").read_text(encoding="utf-8"))["schema"] == 1
    registry = load_registry(out)
    assert registry.warnings == ()
    root = registry.structure_for_extension(".brushes")
    assert root is not None
    kinds = {type(n) for n in root.children}
    assert kinds == {IterativeFieldDef, ConditionFieldDef}
    iterative = root.children[0]
    assert isinstance(iterative, IterativeFieldDef)
    assert isinstance(iterative.children[0], FieldDef)


def test_main_rejects_missing_directory(tmp_path: Path) -> None:
    assert conv.main([str(tmp_path / "nope")]) == 2


@pytest.mark.parametrize(
    ("count_key", "expected"),
    [("stageCount", "stage"), ("NumStrings", "Strings"), ("numPoints", "points"), ("x", "x")],
)
def test_strip_count(count_key: str, expected: str) -> None:
    assert conv._strip_count(count_key) == expected
