"""Unit tests for the Definition loader and Registry."""

from __future__ import annotations

import json
from pathlib import Path

from soase_validator.engine.registry import (
    ConditionReferenceDef,
    FieldDef,
    IterativeFieldDef,
    load_registry,
    load_registry_from_texts,
)

GOOD = {
    "structures": [
        {
            "name": "Root",
            "extension": ".Foo",
            "children": [
                {"name": "a", "type": "Integer", "required": True, "version": "Rebellion194"},
                {"node": "iterative_field", "name": "star", "count_key": "starCount", "limit": 5},
                {"node": "structure_reference", "name": "inner", "structure": "Later"},
                {
                    "node": "condition_reference",
                    "name": "c",
                    "selector": "a",
                    "cases": {"1": "Later"},
                },
            ],
        },
        {"name": "Later", "children": []},
    ],
    "element_rules": [{"name": "Rule", "validation": "Integer", "limit": 3}],
}
ENUMS = {"enums": [{"name": "E", "values": ["X", {"name": "Y", "version": "Rebellion194"}]}]}


def test_queries_and_forward_reference() -> None:
    reg = load_registry_from_texts({"a.json": json.dumps(GOOD), "enums.json": json.dumps(ENUMS)})
    assert reg.warnings == ()
    root = reg.structure("Root")
    assert root is not None
    assert isinstance(root.children[0], FieldDef) and root.children[0].required
    assert isinstance(root.children[1], IterativeFieldDef) and root.children[1].limit == 5
    assert isinstance(root.children[3], ConditionReferenceDef)
    assert reg.structure_for_extension("foo") is root
    assert reg.structure_for_extension(".FOO") is root
    rule = reg.element_rule("Rule")
    assert rule is not None and rule.limit == 3
    enum = reg.enum("E")
    assert enum is not None and enum.values[1].version == "Rebellion194"
    assert reg.structure("Missing") is None


def test_malformed_and_dangling_do_not_block_loading() -> None:
    dangling = {
        "structures": [
            {
                "name": "S",
                "children": [
                    {"node": "structure_reference", "name": "r", "structure": "Nope"},
                    {"node": "bogus", "name": "z"},
                ],
            },
            {"children": []},
        ]
    }
    reg = load_registry_from_texts(
        {"bad.json": "{not json", "d.json": json.dumps(dangling), "a.json": json.dumps(GOOD)}
    )
    assert reg.structure("Root") is not None
    assert reg.structure("S") is not None
    assert {w.file for w in reg.warnings} == {"bad.json", "d.json"}
    assert all(w.code == "SOASE-D001" for w in reg.warnings)
    assert len(reg.warnings) == 4


def test_load_from_directory_and_bundled(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text(json.dumps(GOOD), encoding="utf-8")
    assert load_registry(tmp_path).structure("Root") is not None
    assert load_registry().warnings == ()


def test_field_constraint_is_carried() -> None:
    data = {
        "structures": [
            {
                "name": "S",
                "children": [
                    {"name": "box", "validation": "Position", "constraint": "count=4"},
                    {"name": "plain", "validation": "Position"},
                ],
            }
        ]
    }
    reg = load_registry_from_texts({"s.json": json.dumps(data)})
    assert reg.warnings == ()
    struct = reg.structure("S")
    assert struct is not None
    box, plain = struct.children
    assert isinstance(box, FieldDef) and box.constraint == "count=4"
    assert isinstance(plain, FieldDef) and plain.constraint is None


def test_field_values_from_is_carried_and_malformed_path_warns() -> None:
    data = {
        "structures": [
            {
                "name": "S",
                "children": [
                    {"name": "owner", "validation": "Any", "values_from": "player.designName"},
                    {"name": "plain", "validation": "Any"},
                    {"name": "bad", "validation": "Any", "values_from": "player"},
                ],
            }
        ]
    }
    reg = load_registry_from_texts({"s.json": json.dumps(data)})
    assert [w.element for w in reg.warnings] == ["S.bad"]
    struct = reg.structure("S")
    assert struct is not None
    owner, plain = struct.children
    assert isinstance(owner, FieldDef) and owner.values_from == "player.designName"
    assert isinstance(plain, FieldDef) and plain.values_from is None
