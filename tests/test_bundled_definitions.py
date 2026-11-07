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


_NODE_KINDS: dict[str, type] = {
    "field": FieldDef,
    "iterative_field": IterativeFieldDef,
    "condition_field": ConditionFieldDef,
    "structure_reference": StructureReferenceDef,
}

#: Node attributes compared only when the `verify` entry names them.
_VERIFY_ATTRS = ("validation", "type", "count_key", "version", "values_from")


def _verify_scope(reg: Registry, check: dict) -> tuple[Node, ...]:
    """Return the nodes a `verify` entry searches.

    Args:
        reg: Loaded Definitions.
        check: The `verify` entry.

    Returns:
        The structure's children, or the children of one branch of one of its
        condition fields when the entry has `branch` (and `selector` to name
        the condition field when the structure has several).
    """
    structure = reg.structure(check["structure"])
    assert structure is not None, check
    nodes = structure.children
    if "branch" in check:
        selectors = [
            n
            for n in nodes
            if isinstance(n, ConditionFieldDef) and n.name == check.get("selector", n.name)
        ]
        (selector,) = selectors
        nodes = selector.branches[check["branch"]]
    return nodes


def _verify_matches(node: Node, check: dict) -> bool:
    """Tell whether a node is one a `verify` entry counts.

    Args:
        node: A Definition node.
        check: The `verify` entry.

    Returns:
        True when kind, name and every attribute the entry names match.
    """
    kind = _NODE_KINDS[check.get("node", "field")]
    if not isinstance(node, kind) or node.name != check["field"]:
        return False
    if any(attr in check and getattr(node, attr, None) != check[attr] for attr in _VERIFY_ATTRS):
        return False
    if isinstance(node, FieldDef):
        if node.constraint != check.get("constraint"):
            return False
        if not all(v in (node.values or ()) for v in check.get("values_include", ())):
            return False
        if "values" in check and node.values != tuple(check["values"]):
            return False
    return True


def _run_verify(reg: Registry, check: dict) -> None:
    """Assert one PROVENANCE `verify` entry against the registry.

    Besides the field search (`structure`, `field`, `count` with optional
    `node`, `validation`, `type`, `count_key`, `version`, `constraint`,
    `values` (exact), `values_from`, `values_include`, `branch`, `selector`),
    an entry can check a structure's
    `extension`, its `child_names` or `first_child`, the declared order of the
    gates of same-named children (`field` plus `versions_in_order`), or an
    enumeration (`enum` plus `members`).

    Args:
        reg: Loaded Definitions.
        check: The `verify` entry.
    """
    if "enum" in check:
        enum = reg.enum(check["enum"])
        assert enum is not None, check
        assert [m.name for m in enum.values] == check["members"], check
        return
    structure = reg.structure(check["structure"])
    assert structure is not None, check
    if "extension" in check:
        assert structure.extension == check["extension"], check
        if check["extension"] is not None:
            assert reg.structure_for_extension(check["extension"]) is structure, check
    elif "child_names" in check:
        assert [n.name for n in structure.children] == check["child_names"], check
    elif "first_child" in check:
        assert structure.children[0].name == check["first_child"], check
    elif "versions_in_order" in check:
        same = [n.version for n in structure.children if n.name == check["field"]]
        assert same == check["versions_in_order"], check
    else:
        found = [n for n in _walk(_verify_scope(reg, check)) if _verify_matches(n, check)]
        assert len(found) == check["count"], check


def test_every_audit_correction_is_present_in_the_bundled_json() -> None:
    """Each PROVENANCE `verify` entry matches the registry, so a revert fails.

    A `verify` entry names a registry structure and what it must hold (see
    ``_run_verify``). Re-running the converter into the bundled directory would
    drop the corrections and fail here.
    """
    reg = load_registry()
    for entry in _read("PROVENANCE.json")["audit_corrections"]:
        assert entry.get("verify"), entry["structure"]
        for check in entry["verify"]:
            _run_verify(reg, check)


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
    """Check that every Position field carries its fixed item count.

    ``pixelBox``, ``area`` and ``mainViewIconAreaOffsetFromCenter`` hold 4
    integers, ``pos`` holds 2. The structures that are only XML sources of
    inlined fields (``BrushType``, ``GalaxyStarType``, ``GalaxyPlanetType``,
    ``ResearchBlock``) take the same count as the fields they feed.
    """
    reg = load_registry()
    expected = {
        "pixelBox": "count=4",
        "area": "count=4",
        "pos": "count=2",
        "mainViewIconAreaOffsetFromCenter": "count=4",
    }
    position_fields: list[tuple[str, FieldDef]] = []
    for sname in reg.structure_names:
        structure = reg.structure(sname)
        assert structure is not None
        position_fields.extend(
            (sname, f)
            for f in _walk(structure.children)
            if isinstance(f, FieldDef) and f.validation == "Position"
        )
    assert {f.name for _, f in position_fields} == set(expected)
    for sname, field in position_fields:
        assert field.constraint == expected[field.name], (sname, field.name)
    orphans = {
        (s, f.name)
        for s, f in position_fields
        if s in {"BrushType", "GalaxyStarType", "GalaxyPlanetType", "ResearchBlock"}
    }
    assert orphans == {
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
    assert rules["galaxy.manifest"]["neverGoverned"] == ["FrontEnd.galaxy"]
    for rule in rules.values():
        assert all(isinstance(n, str) for n in rule.get("unlistedByBaseGame", []))
        assert all(isinstance(n, str) for n in rule.get("neverGoverned", []))


def test_versions_file_present() -> None:
    versions = _read("versions.json")
    assert versions["audit_status"]["rebellion-1.98"] == "audited"
    assert "overrides" in versions
