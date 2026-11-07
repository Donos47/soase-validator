"""Definition loader and read-only Registry.

Definitions are bundled JSON files. Each structure file has the form::

    {
      "schema": 1,
      "structures": [
        {"name": "Foo", "extension": ".foo", "version": null, "help": null,
         "children": [{"node": "field", "name": "bar", "type": "Integer"}]}
      ],
      "element_rules": [{"name": "Rule", "validation": "Integer"}]
    }

Child nodes carry a ``node`` tag: ``field``, ``iterative_field``,
``condition_field``, ``structure_reference`` or ``condition_reference``.
``enums.json`` holds ``{"enums": [{"name": "E", "values": ["A", {"name":
"B", "version": "Rebellion194", "help": "..."}]}]}``.

Malformed files, malformed elements and dangling structure references yield
a :class:`LoadWarning` (code ``SOASE-D001``); loading continues.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import Any

from soase_validator.engine.diagnostics import D001

NON_STRUCTURE_FILES = frozenset(
    {"enums.json", "versions.json", "manifest_rules.json", "provenance.json"}
)


@dataclass(frozen=True, slots=True)
class LoadWarning:
    """A non-fatal problem found while loading Definitions.

    Attributes:
        file: Name of the Definition file.
        element: Name or description of the offending element.
        message: Human-readable description.
        code: Diagnostic code, always ``SOASE-D001``.
    """

    file: str
    element: str
    message: str
    code: str = D001


@dataclass(frozen=True, slots=True)
class FieldDef:
    """A single key with a value.

    Attributes:
        name: Key name.
        type: Enum name or validation type.
        validation: Primitive or reference validation type.
        values: Inline allowed values, if any.
        required: Whether the key must be present.
        version: Version gate expression.
        help: Help text.
        constraint: Extra constraint expression.
        values_from: Dotted key path from the file root (for example
            ``player.designName``) naming string values declared elsewhere in
            the same file; those values are allowed in addition to ``values``.
    """

    name: str
    type: str | None = None
    validation: str | None = None
    values: tuple[str, ...] | None = None
    required: bool = False
    version: str | None = None
    help: str | None = None
    constraint: str | None = None
    values_from: str | None = None


@dataclass(frozen=True, slots=True)
class IterativeFieldDef:
    """A count key followed by that many repeated blocks or values.

    Attributes:
        name: Name of the repeated key or block.
        count_key: Key holding the repeat count.
        limit: Maximum count, or None for unlimited.
        required: Whether the count key must be present.
        version: Version gate expression.
        help: Help text.
        type: Value type for repeated value lines.
        validation: Validation type for repeated value lines.
        children: Nodes of each repeated block.
    """

    name: str
    count_key: str
    limit: int | None = None
    required: bool = False
    version: str | None = None
    help: str | None = None
    type: str | None = None
    validation: str | None = None
    children: tuple[Node, ...] = ()


@dataclass(frozen=True, slots=True)
class ConditionFieldDef:
    """A selector field whose value chooses a branch of further nodes.

    Attributes:
        name: Selector key name.
        type: Enum name or validation type of the selector.
        validation: Validation type of the selector.
        branches: Mapping of selector value to branch nodes.
        required: Whether the selector must be present.
        version: Version gate expression.
        help: Help text.
    """

    name: str
    type: str | None = None
    validation: str | None = None
    branches: Mapping[str, tuple[Node, ...]] | None = None
    required: bool = False
    version: str | None = None
    help: str | None = None


@dataclass(frozen=True, slots=True)
class StructureReferenceDef:
    """A key whose block is described by another named structure.

    Attributes:
        name: Key name.
        structure: Name of the referenced structure.
        required: Whether the block must be present.
        version: Version gate expression.
        help: Help text.
    """

    name: str
    structure: str
    required: bool = False
    version: str | None = None
    help: str | None = None


@dataclass(frozen=True, slots=True)
class ConditionReferenceDef:
    """A selector whose value chooses which structure describes a block.

    Attributes:
        name: Key name of the block.
        selector: Key name of the selector field.
        cases: Mapping of selector value to structure name.
        required: Whether the block must be present.
        version: Version gate expression.
        help: Help text.
    """

    name: str
    selector: str
    cases: Mapping[str, str]
    required: bool = False
    version: str | None = None
    help: str | None = None


@dataclass(frozen=True, slots=True)
class ElementRuleDef:
    """A named reusable rule for a value.

    Attributes:
        name: Rule name.
        type: Enum name or validation type.
        validation: Validation type.
        values: Inline allowed values, if any.
        limit: Numeric limit, if any.
        version: Version gate expression.
        help: Help text.
        constraint: Extra constraint expression.
    """

    name: str
    type: str | None = None
    validation: str | None = None
    values: tuple[str, ...] | None = None
    limit: int | None = None
    version: str | None = None
    help: str | None = None
    constraint: str | None = None


Node = (
    FieldDef | IterativeFieldDef | ConditionFieldDef | StructureReferenceDef | ConditionReferenceDef
)


@dataclass(frozen=True, slots=True)
class StructureDef:
    """A named set of nodes describing one block or file type.

    Attributes:
        name: Structure name.
        children: Ordered child nodes.
        extension: File extension (lowercase, leading dot) for root structures.
        version: Version gate expression.
        help: Help text.
    """

    name: str
    children: tuple[Node, ...] = ()
    extension: str | None = None
    version: str | None = None
    help: str | None = None


@dataclass(frozen=True, slots=True)
class EnumValueDef:
    """One member of an enumeration.

    Attributes:
        name: Member text.
        version: Version gate expression.
        help: Help text.
    """

    name: str
    version: str | None = None
    help: str | None = None


@dataclass(frozen=True, slots=True)
class EnumDef:
    """A named enumeration.

    Attributes:
        name: Enumeration name.
        values: Members in declared order.
        version: Version gate expression for the whole enumeration.
        help: Help text.
    """

    name: str
    values: tuple[EnumValueDef, ...] = ()
    version: str | None = None
    help: str | None = None


class _BadElementError(Exception):
    """Internal: a malformed element, carrying a message."""


def _opt_str(raw: Mapping[str, Any], key: str) -> str | None:
    """Read an optional string attribute.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The string or None.

    Raises:
        _BadElementError: If the value is present but not a string.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _BadElementError(f"attribute '{key}' must be a string")
    return value


def _req_str(raw: Mapping[str, Any], key: str) -> str:
    """Read a required non-empty string attribute.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The string.

    Raises:
        _BadElementError: If missing, empty or not a string.
    """
    value = _opt_str(raw, key)
    if not value:
        raise _BadElementError(f"missing attribute '{key}'")
    return value


def _opt_int(raw: Mapping[str, Any], key: str) -> int | None:
    """Read an optional integer attribute.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The integer or None.

    Raises:
        _BadElementError: If the value is not an integer.
    """
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _BadElementError(f"attribute '{key}' must be an integer")
    return value


def _key_path(raw: Mapping[str, Any], key: str) -> str | None:
    """Read an optional dotted key path such as ``player.designName``.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The path or None.

    Raises:
        _BadElementError: If the value is not a string of two or more
            non-empty dot-separated parts.
    """
    value = _opt_str(raw, key)
    if value is None:
        return None
    parts = value.split(".")
    if len(parts) < 2 or not all(parts):
        raise _BadElementError(f"attribute '{key}' must be a dotted key path")
    return value


def _bool(raw: Mapping[str, Any], key: str) -> bool:
    """Read an optional boolean attribute, defaulting to False.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The boolean value.

    Raises:
        _BadElementError: If the value is not a boolean.
    """
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise _BadElementError(f"attribute '{key}' must be a boolean")
    return value


def _values(raw: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Read an optional list of strings under ``values``.

    Args:
        raw: Source mapping.

    Returns:
        A tuple of strings or None.

    Raises:
        _BadElementError: If the value is not a list of strings.
    """
    value = raw.get("values")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _BadElementError("attribute 'values' must be a list of strings")
    return tuple(value)


def _children(raw: Mapping[str, Any], key: str) -> list[Any]:
    """Read a list of raw child nodes.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The raw list (empty when absent).

    Raises:
        _BadElementError: If the value is not a list.
    """
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise _BadElementError(f"attribute '{key}' must be a list")
    return value


def _str_map(raw: Mapping[str, Any], key: str) -> dict[str, str]:
    """Read a string-to-string mapping.

    Args:
        raw: Source mapping.
        key: Attribute name.

    Returns:
        The mapping.

    Raises:
        _BadElementError: If missing or not a string mapping.
    """
    value = raw.get(key)
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise _BadElementError(f"attribute '{key}' must be an object of strings")
    return dict(value)


class _Loader:
    """Collects warnings while converting raw JSON into Definition objects."""

    def __init__(self, file: str, warnings: list[LoadWarning]) -> None:
        """Create a loader for one file.

        Args:
            file: File name used in warnings.
            warnings: Shared warning list.

        Returns:
            None.

        Raises:
            None.
        """
        self.file = file
        self.warnings = warnings

    def warn(self, element: str, message: str) -> None:
        """Record a warning.

        Args:
            element: Offending element name.
            message: Description.

        Returns:
            None.

        Raises:
            None.
        """
        self.warnings.append(LoadWarning(self.file, element, message))

    def node(self, raw: Any) -> Node:
        """Convert one raw child node.

        Args:
            raw: Decoded JSON object.

        Returns:
            The Definition node.

        Raises:
            _BadElementError: If the node is malformed.
        """
        if not isinstance(raw, dict):
            raise _BadElementError("node must be an object")
        kind = raw.get("node", "field")
        name = _req_str(raw, "name")
        common = {
            "required": _bool(raw, "required"),
            "version": _opt_str(raw, "version"),
            "help": _opt_str(raw, "help"),
        }
        if kind == "field":
            return FieldDef(
                name=name,
                type=_opt_str(raw, "type"),
                validation=_opt_str(raw, "validation"),
                values=_values(raw),
                constraint=_opt_str(raw, "constraint"),
                values_from=_key_path(raw, "values_from"),
                **common,
            )
        if kind == "iterative_field":
            return IterativeFieldDef(
                name=name,
                count_key=_opt_str(raw, "count_key") or f"{name}Count",
                limit=_opt_int(raw, "limit"),
                type=_opt_str(raw, "type"),
                validation=_opt_str(raw, "validation"),
                children=self.nodes(_children(raw, "children"), name),
                **common,
            )
        if kind == "condition_field":
            branches_raw = raw.get("branches", {})
            if not isinstance(branches_raw, dict):
                raise _BadElementError("attribute 'branches' must be an object")
            branches: dict[str, tuple[Node, ...]] = {}
            for value, items in branches_raw.items():
                if not isinstance(items, list):
                    raise _BadElementError(f"branch '{value}' must be a list")
                branches[value] = self.nodes(items, f"{name}={value}")
            return ConditionFieldDef(
                name=name,
                type=_opt_str(raw, "type"),
                validation=_opt_str(raw, "validation"),
                branches=branches,
                **common,
            )
        if kind == "structure_reference":
            return StructureReferenceDef(name=name, structure=_req_str(raw, "structure"), **common)
        if kind == "condition_reference":
            return ConditionReferenceDef(
                name=name,
                selector=_req_str(raw, "selector"),
                cases=_str_map(raw, "cases"),
                **common,
            )
        raise _BadElementError(f"unknown node type '{kind}'")

    def nodes(self, raws: list[Any], owner: str) -> tuple[Node, ...]:
        """Convert child nodes, warning about and skipping malformed ones.

        Args:
            raws: Raw child list.
            owner: Owning element name, for warnings.

        Returns:
            The valid nodes in order.

        Raises:
            None.
        """
        result: list[Node] = []
        for raw in raws:
            try:
                result.append(self.node(raw))
            except _BadElementError as exc:
                label = raw.get("name") if isinstance(raw, dict) else None
                self.warn(f"{owner}.{label}" if label else owner, str(exc))
        return tuple(result)

    def structure(self, raw: Any) -> StructureDef:
        """Convert a raw structure.

        Args:
            raw: Decoded JSON object.

        Returns:
            The structure.

        Raises:
            _BadElementError: If the structure itself is malformed.
        """
        if not isinstance(raw, dict):
            raise _BadElementError("structure must be an object")
        name = _req_str(raw, "name")
        ext = _opt_str(raw, "extension")
        return StructureDef(
            name=name,
            children=self.nodes(_children(raw, "children"), name),
            extension=ext.lower() if ext else None,
            version=_opt_str(raw, "version"),
            help=_opt_str(raw, "help"),
        )

    def element_rule(self, raw: Any) -> ElementRuleDef:
        """Convert a raw element rule.

        Args:
            raw: Decoded JSON object.

        Returns:
            The element rule.

        Raises:
            _BadElementError: If malformed.
        """
        if not isinstance(raw, dict):
            raise _BadElementError("element rule must be an object")
        return ElementRuleDef(
            name=_req_str(raw, "name"),
            type=_opt_str(raw, "type"),
            validation=_opt_str(raw, "validation"),
            values=_values(raw),
            limit=_opt_int(raw, "limit"),
            version=_opt_str(raw, "version"),
            help=_opt_str(raw, "help"),
            constraint=_opt_str(raw, "constraint"),
        )

    def enum(self, raw: Any) -> EnumDef:
        """Convert a raw enumeration.

        Args:
            raw: Decoded JSON object.

        Returns:
            The enumeration.

        Raises:
            _BadElementError: If malformed.
        """
        if not isinstance(raw, dict):
            raise _BadElementError("enum must be an object")
        members: list[EnumValueDef] = []
        for item in _children(raw, "values"):
            if isinstance(item, str):
                members.append(EnumValueDef(item))
            elif isinstance(item, dict):
                members.append(
                    EnumValueDef(
                        _req_str(item, "name"),
                        _opt_str(item, "version"),
                        _opt_str(item, "help"),
                    )
                )
            else:
                raise _BadElementError("enum value must be a string or object")
        return EnumDef(
            name=_req_str(raw, "name"),
            values=tuple(members),
            version=_opt_str(raw, "version"),
            help=_opt_str(raw, "help"),
        )


class Registry:
    """Read-only set of loaded Definitions.

    Build one with :func:`load_registry` or :func:`load_registry_from_texts`.
    """

    def __init__(
        self,
        structures: Mapping[str, StructureDef],
        element_rules: Mapping[str, ElementRuleDef],
        enums: Mapping[str, EnumDef],
        warnings: Iterable[LoadWarning] = (),
        structure_files: Mapping[str, str] | None = None,
    ) -> None:
        """Create a Registry.

        Args:
            structures: Structures by name.
            element_rules: Element rules by name.
            enums: Enumerations by name.
            warnings: Load warnings gathered while building.
            structure_files: Structure name mapped to its source file name.

        Returns:
            None.

        Raises:
            None.
        """
        self._structure_files = dict(structure_files or {})
        self._structures = dict(structures)
        self._element_rules = dict(element_rules)
        self._enums = dict(enums)
        self._by_ext = {s.extension: s for s in self._structures.values() if s.extension}
        self.warnings: tuple[LoadWarning, ...] = tuple(warnings)

    def structure(self, name: str) -> StructureDef | None:
        """Look up a structure by name.

        Args:
            name: Structure name.

        Returns:
            The structure or None.

        Raises:
            None.
        """
        return self._structures.get(name)

    def structure_file(self, name: str) -> str | None:
        """Return the Definition file a structure was loaded from.

        Args:
            name: Structure name.

        Returns:
            The file name, or None when unknown.

        Raises:
            None.
        """
        return self._structure_files.get(name)

    @property
    def element_rule_names(self) -> tuple[str, ...]:
        """Names of all loaded element rules, sorted."""
        return tuple(sorted(self._element_rules))

    def element_rule(self, name: str) -> ElementRuleDef | None:
        """Look up an element rule by name.

        Args:
            name: Rule name.

        Returns:
            The rule or None.

        Raises:
            None.
        """
        return self._element_rules.get(name)

    def structure_for_extension(self, ext: str) -> StructureDef | None:
        """Look up the root structure for a file extension.

        Args:
            ext: Extension with or without a leading dot, any case.

        Returns:
            The structure or None.

        Raises:
            None.
        """
        ext = ext.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        return self._by_ext.get(ext)

    def enum(self, name: str) -> EnumDef | None:
        """Look up an enumeration by name.

        Args:
            name: Enumeration name.

        Returns:
            The enumeration or None.

        Raises:
            None.
        """
        return self._enums.get(name)

    @property
    def structure_names(self) -> tuple[str, ...]:
        """Names of all loaded structures, sorted."""
        return tuple(sorted(self._structures))

    @property
    def enum_names(self) -> tuple[str, ...]:
        """Names of all loaded enumerations, sorted."""
        return tuple(sorted(self._enums))


_NODE_KINDS: dict[type, str] = {
    FieldDef: "field",
    IterativeFieldDef: "iterative_field",
    ConditionFieldDef: "condition_field",
    StructureReferenceDef: "structure_reference",
    ConditionReferenceDef: "condition_reference",
}


def _node_to_json(node: Node) -> dict[str, Any]:
    """Convert a Definition node to its bundled JSON form.

    Args:
        node: The node.

    Returns:
        A JSON-compatible mapping; unset and false attributes are omitted.
    """
    result: dict[str, Any] = {"node": _NODE_KINDS[type(node)]}
    for item in fields(node):
        value = getattr(node, item.name)
        if value is None or value is False or value == ():
            continue
        if item.name == "children":
            value = [_node_to_json(child) for child in value]
        elif item.name == "branches":
            value = {key: [_node_to_json(child) for child in items] for key, items in value.items()}
        elif item.name == "cases":
            value = dict(value)
        elif isinstance(value, tuple):
            value = list(value)
        result[item.name] = value
    return result


def structure_to_json(structure: StructureDef) -> dict[str, Any]:
    """Convert a structure to its bundled JSON form.

    Args:
        structure: The structure.

    Returns:
        A JSON-compatible mapping with the structure's attributes and
        children; unset attributes are omitted.
    """
    result: dict[str, Any] = {"name": structure.name}
    for key in ("extension", "version", "help"):
        value = getattr(structure, key)
        if value is not None:
            result[key] = value
    result["children"] = [_node_to_json(child) for child in structure.children]
    return result


def _walk(nodes: Iterable[Node]) -> Iterable[Node]:
    """Yield every node in a tree, depth first.

    Args:
        nodes: Top-level nodes.

    Returns:
        An iterator over all nodes including nested ones.

    Raises:
        None.
    """
    for node in nodes:
        yield node
        if isinstance(node, IterativeFieldDef):
            yield from _walk(node.children)
        elif isinstance(node, ConditionFieldDef):
            for branch in (node.branches or {}).values():
                yield from _walk(branch)


def _check_references(
    structures: Mapping[str, StructureDef],
    structure_files: Mapping[str, str],
    warnings: list[LoadWarning],
) -> None:
    """Second pass: warn about references to unknown structures.

    Args:
        structures: Structures by name.
        structure_files: Structure name mapped to its source file.
        warnings: Warning list to extend.

    Returns:
        None.

    Raises:
        None.
    """
    for struct in structures.values():
        file = structure_files[struct.name]
        for node in _walk(struct.children):
            targets: list[str] = []
            if isinstance(node, StructureReferenceDef):
                targets = [node.structure]
            elif isinstance(node, ConditionReferenceDef):
                targets = list(node.cases.values())
            for target in targets:
                if target not in structures:
                    warnings.append(
                        LoadWarning(
                            file,
                            f"{struct.name}.{node.name}",
                            f"reference to unknown structure '{target}'",
                        )
                    )


def _collect(
    loader: _Loader,
    data: Mapping[str, Any],
    key: str,
    convert: Callable[[Any], Any],
    store: dict[str, Any],
) -> None:
    """Convert each raw item under ``key`` into ``store`` keyed by name.

    Args:
        loader: Loader for the current file.
        data: Decoded top-level JSON object.
        key: Key holding the list of raw items.
        convert: Conversion function for one item.
        store: Destination mapping; duplicates keep the first definition.

    Returns:
        None.

    Raises:
        None. Problems become warnings.
    """
    items = data.get(key, [])
    if not isinstance(items, list):
        loader.warn(key, f"'{key}' must be a list")
        return
    for raw in items:
        label = raw.get("name") if isinstance(raw, dict) else None
        try:
            obj = convert(raw)
        except _BadElementError as exc:
            loader.warn(str(label or key), str(exc))
            continue
        if obj.name in store:
            loader.warn(obj.name, "duplicate name; first definition kept")
            continue
        store[obj.name] = obj


def load_registry_from_texts(files: Mapping[str, str]) -> Registry:
    """Build a Registry from Definition file contents.

    Args:
        files: File name mapped to JSON text. ``enums.json`` is read as
            enumerations; other recognised data files are ignored; all
            remaining files are read as structure files.

    Returns:
        The Registry, with any problems in ``warnings``.

    Raises:
        None. Malformed input becomes a LoadWarning.
    """
    warnings: list[LoadWarning] = []
    structures: dict[str, StructureDef] = {}
    structure_files: dict[str, str] = {}
    rules: dict[str, ElementRuleDef] = {}
    enums: dict[str, EnumDef] = {}

    for file in sorted(files):
        if file.lower() in NON_STRUCTURE_FILES and file.lower() != "enums.json":
            continue
        loader = _Loader(file, warnings)
        try:
            data = json.loads(files[file])
        except (json.JSONDecodeError, RecursionError) as exc:
            loader.warn(file, f"malformed JSON: {exc}")
            continue
        if not isinstance(data, dict):
            loader.warn(file, "top-level value must be an object")
            continue

        if file.lower() == "enums.json":
            _collect(loader, data, "enums", loader.enum, enums)
        else:
            before = set(structures)
            _collect(loader, data, "structures", loader.structure, structures)
            structure_files.update({n: file for n in set(structures) - before})
            _collect(loader, data, "element_rules", loader.element_rule, rules)

    _check_references(structures, structure_files, warnings)
    return Registry(structures, rules, enums, warnings, structure_files)


def load_registry(directory: Path | None = None) -> Registry:
    """Load a Registry from a directory of JSON files.

    Args:
        directory: Directory to read. Defaults to the bundled
            ``soase_validator.definitions`` package data.

    Returns:
        The Registry. Unreadable files become LoadWarnings.

    Raises:
        None.
    """
    files: dict[str, str] = {}
    warnings: list[LoadWarning] = []
    if directory is None:
        entries = [
            (p.name, p)
            for p in resources.files("soase_validator.definitions").iterdir()
            if p.name.endswith(".json")
        ]
    else:
        entries = [(p.name, p) for p in sorted(directory.glob("*.json"))]
    for name, entry in entries:
        try:
            files[name] = entry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(LoadWarning(name, name, f"cannot read file: {exc}"))
    registry = load_registry_from_texts(files)
    if warnings:
        registry.warnings = (*warnings, *registry.warnings)
    return registry
