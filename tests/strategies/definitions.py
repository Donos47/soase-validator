"""Hypothesis strategies and helpers for Definitions.

``definitions()`` generates a :class:`DefinitionSet`: structure graphs using
every node type, element rules, version gates and enums. Names are unique
and every structure reference points at a generated structure, so the
serialized files load with zero warnings.

Helpers for other tests:

* :func:`serialize` turns a ``DefinitionSet`` into ``dict[str, str]`` (file
  name to JSON text) in the bundled schema, ready for
  ``load_registry_from_texts``.
* :func:`registry_differences` compares a ``DefinitionSet`` with a loaded
  ``Registry`` and lists any mismatches (empty list means equal).
* :func:`load` serializes and loads in one step.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass
from typing import Any

from hypothesis import strategies as st

from soase_validator.engine.registry import (
    ConditionFieldDef,
    ConditionReferenceDef,
    ElementRuleDef,
    EnumDef,
    EnumValueDef,
    FieldDef,
    IterativeFieldDef,
    Node,
    Registry,
    StructureDef,
    StructureReferenceDef,
    load_registry_from_texts,
)

VALIDATION_TYPES = (
    "Boolean",
    "Integer",
    "Decimal",
    "Color",
    "Position",
    "Coordinate",
    "Orientation",
    "Any",
)
VERSION_GATES = (
    "Vanilla",
    "Entrenchment",
    "Diplomacy",
    "Rebellion",
    "Rebellion185",
    "Rebellion193",
    "Rebellion194",
)
MAX_DEPTH = 2
ENUMS_FILE = "enums.json"


@dataclass(frozen=True, slots=True)
class DefinitionSet:
    """A generated set of Definitions.

    Attributes:
        structures: Structures in declaration order.
        element_rules: Element rules in declaration order.
        enums: Enumerations in declaration order.
    """

    structures: tuple[StructureDef, ...] = ()
    element_rules: tuple[ElementRuleDef, ...] = ()
    enums: tuple[EnumDef, ...] = ()


# ---------------------------------------------------------------- strategies

_identifiers = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=8).map(
    lambda s: "N" + s
)
_gates = st.none() | st.sampled_from(VERSION_GATES)
_help = st.none() | st.text(alphabet=string.ascii_letters + " .,", min_size=1, max_size=20)
_type_name = st.none() | st.sampled_from(VALIDATION_TYPES)
_value_text = st.text(alphabet=string.ascii_letters + string.digits + "_", min_size=1, max_size=8)
_values = st.none() | st.lists(_value_text, max_size=4, unique=True).map(tuple)


@st.composite
def _nodes(draw: st.DrawFn, structs: list[str], depth: int) -> tuple[Node, ...]:
    """Draw a tuple of child nodes.

    Args:
        draw: Hypothesis draw function.
        structs: Names of all structures; references pick from these.
        depth: Remaining nesting depth for iterative and condition nodes.

    Returns:
        The drawn nodes.

    Raises:
        None.
    """
    kinds = ["field", "structure_reference", "condition_reference"]
    if depth > 0:
        kinds += ["iterative_field", "condition_field"]
    count = draw(st.integers(min_value=0, max_value=4))
    result: list[Node] = []
    for _ in range(count):
        kind = draw(st.sampled_from(kinds))
        name = draw(_identifiers)
        common: dict[str, Any] = {
            "required": draw(st.booleans()),
            "version": draw(_gates),
            "help": draw(_help),
        }
        if kind == "field":
            result.append(
                FieldDef(
                    name=name,
                    type=draw(_type_name),
                    validation=draw(_type_name),
                    values=draw(_values),
                    constraint=draw(_help),
                    **common,
                )
            )
        elif kind == "iterative_field":
            result.append(
                IterativeFieldDef(
                    name=name,
                    count_key=draw(_identifiers),
                    limit=draw(st.none() | st.integers(min_value=0, max_value=1000)),
                    type=draw(_type_name),
                    validation=draw(_type_name),
                    children=draw(_nodes(structs, depth - 1)),
                    **common,
                )
            )
        elif kind == "condition_field":
            keys = draw(st.lists(_value_text, max_size=3, unique=True))
            branches = {key: draw(_nodes(structs, depth - 1)) for key in keys}
            result.append(
                ConditionFieldDef(
                    name=name,
                    type=draw(_type_name),
                    validation=draw(_type_name),
                    branches=branches,
                    **common,
                )
            )
        elif kind == "structure_reference":
            result.append(
                StructureReferenceDef(name=name, structure=draw(st.sampled_from(structs)), **common)
            )
        else:
            cases = draw(
                st.dictionaries(_value_text, st.sampled_from(structs), min_size=1, max_size=3)
            )
            result.append(
                ConditionReferenceDef(name=name, selector=draw(_identifiers), cases=cases, **common)
            )
    return tuple(result)


@st.composite
def _enum(draw: st.DrawFn, name: str) -> EnumDef:
    """Draw one enumeration.

    Args:
        draw: Hypothesis draw function.
        name: Enumeration name.

    Returns:
        The enumeration with unique member names.
    """
    names = draw(st.lists(_value_text, max_size=5, unique=True))
    members = tuple(EnumValueDef(n, draw(_gates), draw(_help)) for n in names)
    return EnumDef(name=name, values=members, version=draw(_gates), help=draw(_help))


@st.composite
def _rule(draw: st.DrawFn, name: str) -> ElementRuleDef:
    """Draw one element rule.

    Args:
        draw: Hypothesis draw function.
        name: Rule name.

    Returns:
        The element rule.
    """
    return ElementRuleDef(
        name=name,
        type=draw(_type_name),
        validation=draw(_type_name),
        values=draw(_values),
        limit=draw(st.none() | st.integers(min_value=0, max_value=1000)),
        version=draw(_gates),
        help=draw(_help),
        constraint=draw(_help),
    )


@st.composite
def definitions(draw: st.DrawFn, max_structures: int = 5) -> DefinitionSet:
    """Generate a loadable set of Definitions.

    Args:
        draw: Hypothesis draw function.
        max_structures: Maximum number of structures.

    Returns:
        A ``DefinitionSet`` with unique structure, rule and enum names,
        unique lowercase extensions, and no dangling structure references.
    """
    names = draw(st.lists(_identifiers, min_size=1, max_size=max_structures, unique=True))
    extensions = draw(
        st.lists(
            st.none() | _identifiers.map(lambda s: "." + s.lower()),
            min_size=len(names),
            max_size=len(names),
        )
    )
    seen: set[str] = set()
    structures: list[StructureDef] = []
    for name, ext in zip(names, extensions, strict=True):
        if ext in seen:
            ext = None
        if ext:
            seen.add(ext)
        structures.append(
            StructureDef(
                name=name,
                children=draw(_nodes(names, MAX_DEPTH)),
                extension=ext,
                version=draw(_gates),
                help=draw(_help),
            )
        )
    rule_names = draw(st.lists(_identifiers, max_size=3, unique=True))
    rules = tuple(draw(_rule(n)) for n in rule_names)
    enum_names = draw(st.lists(_identifiers, max_size=3, unique=True))
    enums = tuple(draw(_enum(n)) for n in enum_names)
    return DefinitionSet(tuple(structures), rules, enums)


# --------------------------------------------------------------- serializer


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """Set ``key`` in ``out`` unless the value is None.

    Args:
        out: Destination mapping.
        key: Key to set.
        value: Value; None is skipped.

    Returns:
        None.

    Raises:
        None.
    """
    if value is not None:
        out[key] = value


def node_to_json(node: Node) -> dict[str, Any]:
    """Serialize one node to the bundled JSON schema.

    Args:
        node: The node.

    Returns:
        A JSON-compatible dict with a ``node`` tag.

    Raises:
        TypeError: If the node type is unknown.
    """
    out: dict[str, Any] = {}
    if isinstance(node, FieldDef):
        out = {"node": "field", "name": node.name}
        _put(out, "type", node.type)
        _put(out, "validation", node.validation)
        _put(out, "values", None if node.values is None else list(node.values))
        _put(out, "constraint", node.constraint)
    elif isinstance(node, IterativeFieldDef):
        out = {"node": "iterative_field", "name": node.name, "count_key": node.count_key}
        _put(out, "limit", node.limit)
        _put(out, "type", node.type)
        _put(out, "validation", node.validation)
        out["children"] = [node_to_json(c) for c in node.children]
    elif isinstance(node, ConditionFieldDef):
        out = {"node": "condition_field", "name": node.name}
        _put(out, "type", node.type)
        _put(out, "validation", node.validation)
        out["branches"] = {
            key: [node_to_json(c) for c in items] for key, items in (node.branches or {}).items()
        }
    elif isinstance(node, StructureReferenceDef):
        out = {"node": "structure_reference", "name": node.name, "structure": node.structure}
    elif isinstance(node, ConditionReferenceDef):
        out = {
            "node": "condition_reference",
            "name": node.name,
            "selector": node.selector,
            "cases": dict(node.cases),
        }
    else:
        raise TypeError(f"unknown node type: {type(node).__name__}")
    out["required"] = node.required
    _put(out, "version", node.version)
    _put(out, "help", node.help)
    return out


def structure_to_json(struct: StructureDef) -> dict[str, Any]:
    """Serialize a structure.

    Args:
        struct: The structure.

    Returns:
        A JSON-compatible dict.

    Raises:
        None.
    """
    return {
        "name": struct.name,
        "extension": struct.extension,
        "version": struct.version,
        "help": struct.help,
        "children": [node_to_json(c) for c in struct.children],
    }


def rule_to_json(rule: ElementRuleDef) -> dict[str, Any]:
    """Serialize an element rule.

    Args:
        rule: The rule.

    Returns:
        A JSON-compatible dict.

    Raises:
        None.
    """
    out: dict[str, Any] = {"name": rule.name}
    _put(out, "type", rule.type)
    _put(out, "validation", rule.validation)
    _put(out, "values", None if rule.values is None else list(rule.values))
    _put(out, "limit", rule.limit)
    _put(out, "version", rule.version)
    _put(out, "help", rule.help)
    _put(out, "constraint", rule.constraint)
    return out


def enum_to_json(enum: EnumDef) -> dict[str, Any]:
    """Serialize an enumeration.

    Args:
        enum: The enumeration.

    Returns:
        A JSON-compatible dict. Members without a gate or help text are
        written as plain strings.

    Raises:
        None.
    """
    members: list[Any] = []
    for member in enum.values:
        if member.version is None and member.help is None:
            members.append(member.name)
        else:
            item: dict[str, Any] = {"name": member.name}
            _put(item, "version", member.version)
            _put(item, "help", member.help)
            members.append(item)
    out: dict[str, Any] = {"name": enum.name, "values": members}
    _put(out, "version", enum.version)
    _put(out, "help", enum.help)
    return out


def serialize(defs: DefinitionSet, structure_files: int = 2) -> dict[str, str]:
    """Serialize Definitions into bundled-schema JSON files.

    Args:
        defs: The generated Definitions.
        structure_files: Number of structure files to spread structures over
            (round robin). Element rules go in the first file.

    Returns:
        File name mapped to JSON text, including ``enums.json``.

    Raises:
        ValueError: If ``structure_files`` is less than 1.
    """
    if structure_files < 1:
        raise ValueError("structure_files must be at least 1")
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(structure_files)]
    for index, struct in enumerate(defs.structures):
        buckets[index % structure_files].append(structure_to_json(struct))
    files: dict[str, str] = {}
    for index, structures in enumerate(buckets):
        doc: dict[str, Any] = {"schema": 1, "structures": structures}
        if index == 0:
            doc["element_rules"] = [rule_to_json(r) for r in defs.element_rules]
        files[f"structures_{index}.json"] = json.dumps(doc)
    files[ENUMS_FILE] = json.dumps({"enums": [enum_to_json(e) for e in defs.enums]})
    return files


def load(defs: DefinitionSet, structure_files: int = 2) -> Registry:
    """Serialize and load Definitions.

    Args:
        defs: The generated Definitions.
        structure_files: Number of structure files.

    Returns:
        The loaded Registry.

    Raises:
        None.
    """
    return load_registry_from_texts(serialize(defs, structure_files))


def registry_differences(defs: DefinitionSet, registry: Registry) -> list[str]:
    """Compare generated Definitions with a loaded Registry.

    Args:
        defs: The generated model.
        registry: The Registry loaded from its serialization.

    Returns:
        Human-readable mismatches; an empty list means they are equal.

    Raises:
        None.
    """
    problems: list[str] = [f"warning: {w.element}: {w.message}" for w in registry.warnings]
    if set(registry.structure_names) != {s.name for s in defs.structures}:
        problems.append("structure names differ")
    if set(registry.enum_names) != {e.name for e in defs.enums}:
        problems.append("enum names differ")
    problems += [
        f"structure {s.name} differs" for s in defs.structures if registry.structure(s.name) != s
    ]
    problems += [
        f"element rule {r.name} differs"
        for r in defs.element_rules
        if registry.element_rule(r.name) != r
    ]
    problems += [f"enum {e.name} differs" for e in defs.enums if registry.enum(e.name) != e]
    for struct in defs.structures:
        if struct.extension and registry.structure_for_extension(struct.extension) != struct:
            problems.append(f"extension {struct.extension} differs")
    return problems
