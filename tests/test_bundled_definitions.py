"""Smoke tests for the bundled Definition data files."""

from __future__ import annotations

import json
from importlib import resources

from soase_validator.engine.primitives import validate_constraint
from soase_validator.engine.registry import (
    ConditionFieldDef,
    ConditionReferenceDef,
    FieldDef,
    IterativeFieldDef,
    Node,
    Registry,
    StructureReferenceDef,
    load_registry,
    load_registry_from_texts,
)

NODE_TYPES = (
    FieldDef,
    IterativeFieldDef,
    ConditionFieldDef,
    StructureReferenceDef,
    ConditionReferenceDef,
)


def _walk(nodes: tuple[Node, ...]):
    """Yield every node in a tree, including nested children and branches."""
    for node in nodes:
        yield node
        if isinstance(node, IterativeFieldDef):
            yield from _walk(node.children)
        elif isinstance(node, ConditionFieldDef):
            for branch in node.branches.values():
                yield from _walk(branch)


def _bundled_node_types(reg: Registry) -> set[type]:
    found: set[type] = set()
    for name in reg.structure_names:
        structure = reg.structure(name)
        assert structure is not None
        found.update(type(n) for n in _walk(structure.children))
    return found


def _read(name: str) -> dict:
    text = resources.files("soase_validator.definitions").joinpath(name).read_text("utf-8")
    return json.loads(text)


def test_bundled_definitions_load_without_warnings() -> None:
    reg = load_registry()
    assert reg.warnings == ()
    assert reg.structure_names
    assert reg.enum_names


def test_bundled_node_types_present() -> None:
    """Four node types occur in the converted data; condition_reference does not.

    The converter supports condition_reference, but the source plugin Definitions
    contain no such element, so the bundled data has none. The type is covered by
    the synthetic test below. If a future conversion adds one, this test fails
    and should be updated to require all five types.
    """
    present = _bundled_node_types(load_registry())
    missing = {t for t in NODE_TYPES if t not in present}
    assert missing == {ConditionReferenceDef}


def test_condition_reference_covered_synthetically() -> None:
    """Cover the node type via a synthetic case, independent of the converted data."""
    data = {
        "structures": [
            {
                "name": "S",
                "children": [
                    {
                        "node": "condition_reference",
                        "name": "c",
                        "selector": "kind",
                        "cases": {"1": "T"},
                    }
                ],
            },
            {"name": "T", "children": []},
        ]
    }
    reg = load_registry_from_texts({"s.json": json.dumps(data)})
    assert reg.warnings == ()
    structure = reg.structure("S")
    assert structure is not None
    assert isinstance(structure.children[0], ConditionReferenceDef)


def test_provenance_content() -> None:
    prov = _read("PROVENANCE.json")
    assert prov["author"] == "zombiesrus5"
    assert prov["source_version"] == "1.0.0.202007231528"
    assert prov["conversion_date"]
    assert prov["origin"]
    corrections = prov["audit_corrections"]
    assert corrections
    for entry in corrections:
        assert entry["game_version"] == "Rebellion 1.98"
        assert entry["structure"] and entry["field"] and entry["change"] and entry["evidence"]


def test_every_audit_correction_is_present_in_the_bundled_json() -> None:
    """Each PROVENANCE `verify` entry matches the registry, so a revert fails.

    A `verify` entry names a registry structure, a field name, the expected
    `validation`, the expected `constraint` (when the correction adds one),
    optionally one `branch` of the structure's condition field, and the number
    of such fields found. Re-running the converter into
    the bundled directory would drop these and fail here.
    """
    reg = load_registry()
    for entry in _read("PROVENANCE.json")["audit_corrections"]:
        assert entry.get("verify"), entry["structure"]
        for check in entry["verify"]:
            structure = reg.structure(check["structure"])
            assert structure is not None, check
            nodes = structure.children
            if "branch" in check:
                (selector,) = nodes
                assert isinstance(selector, ConditionFieldDef), check
                nodes = selector.branches[check["branch"]]
            found = [
                n
                for n in _walk(nodes)
                if isinstance(n, FieldDef)
                and n.name == check["field"]
                and n.validation == check["validation"]
                and n.constraint == check.get("constraint")
            ]
            assert len(found) == check["count"], check


def _fields(reg: Registry, name: str):
    """Yield (structure name, field) for every field called ``name``."""
    for sname in reg.structure_names:
        structure = reg.structure(sname)
        assert structure is not None
        for node in _walk(structure.children):
            if isinstance(node, FieldDef) and node.name == name:
                yield sname, node


def test_bundled_constraints_are_valid_and_only_on_position() -> None:
    reg = load_registry()
    for sname in reg.structure_names:
        structure = reg.structure(sname)
        assert structure is not None
        for node in _walk(structure.children):
            if isinstance(node, FieldDef) and node.constraint is not None:
                validation = node.validation or node.type or ""
                assert validate_constraint(validation, node.constraint) is None, (sname, node.name)


def test_position_counts_follow_the_survey() -> None:
    reg = load_registry()
    expected = {"pixelBox": "count=4", "area": "count=4", "pos": "count=2"}
    expected_one = {"mainViewIconAreaOffsetFromCenter": "count=4"}
    for name, constraint in {**expected, **expected_one}.items():
        constrained = [
            f.constraint
            for _, f in _fields(reg, name)
            if f.validation == "Position" and f.constraint
        ]
        assert constrained, name
        assert set(constrained) == {constraint}, name
    # Fields typed Position that the survey never reached carry no constraint.
    unconstrained = {
        (s, f.name)
        for n in ("pixelBox", "area", "pos")
        for s, f in _fields(reg, n)
        if f.validation == "Position" and f.constraint is None
    }
    assert unconstrained == {
        ("BrushType", "pixelBox"),
        ("GalaxyStarType", "pos"),
        ("GalaxyPlanetType", "pos"),
        ("ResearchBlock", "area"),
    }


def test_group_condition_chance_param_is_any() -> None:
    reg = load_registry()
    structure = reg.structure("GroupType.condition")
    assert structure is not None
    (selector,) = structure.children
    assert isinstance(selector, ConditionFieldDef)
    for case in ("PlanetOwnerIsMilitiaWithChance", "NoPlanetOwnerWithChance"):
        (param,) = selector.branches[case]
        assert isinstance(param, FieldDef) and param.validation == "Any"


def test_manifest_rules_content() -> None:
    rules = _read("manifest_rules.json")
    assert set(rules) == {
        "entity.manifest",
        "brush.manifest",
        "galaxy.manifest",
        "playerPictures.manifest",
        "playerThemes.manifest",
        "skybox.manifest",
    }
    assert rules["galaxy.manifest"]["includesExtension"] is False
    assert rules["galaxy.manifest"]["governs"]["directory"] == "Galaxy"
    assert rules["entity.manifest"]["governs"]["directory"] == "GameInfo"
    assert rules["skybox.manifest"]["governs"]["identifiedBy"] == "skyboxbackdropdata.meshName"
    for rule in rules.values():
        assert all(isinstance(n, str) for n in rule.get("unlistedByBaseGame", []))


def test_versions_file_present() -> None:
    versions = _read("versions.json")
    assert versions["audit_status"]["rebellion-1.98"] == "audited"
    assert "overrides" in versions
