"""Smoke tests for the bundled Definition data files."""

from __future__ import annotations

import json
from importlib import resources

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
    assert prov["audit_corrections"] == []


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
    assert versions["audit_status"]["rebellion-1.96"] == "audited"
    assert "overrides" in versions
