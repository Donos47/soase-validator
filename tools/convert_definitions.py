"""One-off converter from the original zombiesrus5 XML Definitions to bundled JSON.

This is a development-time tool and is not shipped at runtime. It reads the
``*.xml`` Definition files from a directory given on the command line and
writes JSON files in the schema documented in
``soase_validator.engine.registry``, plus ``enums.json``.

Usage::

    uv run python tools/convert_definitions.py <xml-dir> [--output <dir>]
        [--overwrite-corrections]

The converter refuses to write into a directory whose ``PROVENANCE.json``
lists ``audit_corrections`` (the bundled directory), because converting from
XML drops them. ``--overwrite-corrections`` overrides the refusal.

Mapping summary
---------------
* ``structure`` -> a structure entry. Structures nested inside other
  structures, iterative fields or conditions are hoisted into their own
  structure entries named ``Parent.child`` and replaced by a
  ``structure_reference`` node.
* ``field`` -> ``field`` node. Inline ``<value>`` children become ``values``,
  or a hoisted enumeration when a value carries a version gate or help.
* ``structure_reference`` -> ``structure_reference``; the target is the
  ``type`` attribute, or the ``name`` when ``type`` is absent.
* ``iterative_field`` -> ``iterative_field`` with ``count_key`` set to the
  original (count) name and ``name`` set to the repeated key. A repeated
  structure reference is inlined as the block's ``children``.
* An empty ``<value></value>`` is the empty-string member ``""`` (valid in
  field values, element rules and condition selectors). A version or help on
  an empty value is dropped and reported, because the registry requires a
  non-empty name in member objects.
* ``condition_field`` -> ``condition_field`` with one branch per value. When
  a value is defined by more than one ``<condition>``, the later definition
  replaces the earlier one (no merge) and a notice names both. A top-level
  ``condition_field`` is also an enumeration of its values, and
  every field whose ``type`` (or bare name) refers to it is expanded inline.
* ``element_rule`` -> element rule; its value list becomes an enumeration
  of the same name, referenced through the rule's ``type``.
* Version gates and help text are copied verbatim.

Elements that cannot be mapped are recorded in the report and skipped.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: Root structures that describe a non-entity file type, by structure name.
ROOT_EXTENSIONS: dict[str, str] = {
    "Brushes": ".brushes",
    "Constants": ".constants",
    "Explosiondata": ".explosiondata",
    "Galaxy": ".galaxy",
    "GalaxyScenarioDef": ".galaxyScenarioDef",
    "Groups": ".groups",
    "Particle": ".particle",
    "PlanetItemTypeCount": ".planetItemTypeCount",
    "Randomeventdefs": ".randomeventdefs",
    "Sounddata": ".sounddata",
    "Str": ".str",
    "AsteroidDef": ".asteroidDef",
    "Starscape": ".starscapedata",
    "SkyBoxProperties": ".skyboxbackdropdata",
}

#: File stems that would collide with non-structure Definition files.
RESERVED_STEMS = frozenset({"enums", "versions", "manifest_rules", "provenance"})

_COMMON_ATTRS = {"name", "required", "help", "version"}
_ALLOWED_ATTRS: dict[str, set[str]] = {
    "structure": _COMMON_ATTRS | {"ordered"},
    "field": _COMMON_ATTRS | {"type", "validation", "values", "constraint"},
    "iterative_field": _COMMON_ATTRS | {"limit"},
    "structure_reference": _COMMON_ATTRS | {"type"},
    "condition_reference": _COMMON_ATTRS | {"type"},
    "condition_field": _COMMON_ATTRS | {"type"},
    "element_rule": _COMMON_ATTRS | {"type", "validation", "values", "constraint"},
    "condition": {"value", "version", "required"},
}


@dataclass(slots=True)
class Report:
    """Outcome of a conversion run.

    Attributes:
        unconverted: Elements or attributes that could not be converted.
        notices: Informational remarks that need no action.
        skipped_files: XML files that are not Definition files.
    """

    unconverted: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Ctx:
    """Conversion context.

    Attributes:
        file: Source XML file name.
        path: Dotted owner path used to name hoisted structures and enums.
    """

    file: str
    path: str

    def child(self, name: str) -> Ctx:
        """Return a context one level deeper.

        Args:
            name: Child element name.

        Returns:
            The nested context.

        Raises:
            None.
        """
        return Ctx(self.file, f"{self.path}.{name}")


@dataclass(slots=True)
class ConversionResult:
    """Converted Definition data ready to be written.

    Attributes:
        files: Output file name mapped to its JSON document.
        report: Problems and notices found during conversion.
    """

    files: dict[str, dict[str, Any]]
    report: Report


def _put(target: dict[str, Any], key: str, value: Any) -> None:
    """Set ``key`` unless the value is empty.

    Args:
        target: Destination mapping.
        key: Key to set.
        value: Value; None, False and empty strings are skipped.

    Returns:
        None.

    Raises:
        None.
    """
    if value is None or value is False or value == "":
        return
    target[key] = value


def _local(tag: Any) -> str:
    """Strip any XML namespace from a tag.

    Args:
        tag: Element tag.

    Returns:
        The local tag name, or an empty string for non-string tags.

    Raises:
        None.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


class Converter:
    """Converts parsed XML Definition trees into the bundled JSON schema."""

    def __init__(self) -> None:
        """Create an empty converter.

        Returns:
            None.

        Raises:
            None.
        """
        self.report = Report()
        self.struct_elems: dict[str, tuple[str, ET.Element]] = {}
        self.cond_elems: dict[str, tuple[str, ET.Element]] = {}
        self.rule_elems: dict[str, tuple[str, ET.Element]] = {}
        self.file_order: list[str] = []
        self.enums: dict[str, dict[str, Any]] = {}
        self.rule_enum_names: set[str] = set()
        self.entity_types: set[str] = set()
        self._roots: dict[str, dict[str, Any]] = {}
        self._root_file: dict[str, str] = {}
        self._hoisted: list[tuple[str, dict[str, Any]]] = []
        self._cond_branches: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._in_progress: set[str] = set()
        self._inlined: set[str] = set()
        self._used_structs: set[str] = set()
        self._used_enums: set[str] = set()

    # -- reporting -----------------------------------------------------------

    def issue(self, ctx: Ctx | str, where: str, message: str) -> None:
        """Record something that could not be converted.

        Args:
            ctx: Context or file name.
            where: Element description.
            message: What went wrong.

        Returns:
            None.

        Raises:
            None.
        """
        file = ctx.file if isinstance(ctx, Ctx) else ctx
        line = f"{file}: {where}: {message}"
        if line not in self.report.unconverted:
            self.report.unconverted.append(line)

    def notice(self, ctx: Ctx | str, where: str, message: str) -> None:
        """Record an informational remark.

        Args:
            ctx: Context or file name.
            where: Element description.
            message: The remark.

        Returns:
            None.

        Raises:
            None.
        """
        file = ctx.file if isinstance(ctx, Ctx) else ctx
        line = f"{file}: {where}: {message}"
        if line not in self.report.notices:
            self.report.notices.append(line)

    # -- loading -------------------------------------------------------------

    def load_text(self, file: str, text: str) -> None:
        """Parse one XML document and register its top-level elements.

        Args:
            file: File name used in reports and output naming.
            text: XML text.

        Returns:
            None.

        Raises:
            None. Problems are recorded in the report.
        """
        try:
            root = ET.fromstring(text)  # noqa: S314 - local development input
        except ET.ParseError as exc:
            self.issue(file, file, f"malformed XML: {exc}")
            return
        if _local(root.tag) != "entity_definitions":
            self.report.skipped_files.append(file)
            return
        self.file_order.append(file)
        for elem in root:
            tag = _local(elem.tag)
            name = elem.get("name")
            if tag not in ("structure", "condition_field", "element_rule"):
                if tag:
                    self.issue(file, tag, "unsupported top-level element")
                continue
            if not name:
                self.issue(file, tag, "top-level element without a name")
                continue
            self._check_attrs(file, elem)
            table = {
                "structure": self.struct_elems,
                "condition_field": self.cond_elems,
                "element_rule": self.rule_elems,
            }[tag]
            if name in table:
                same = ET.tostring(table[name][1]) == ET.tostring(elem)
                if same:
                    self.notice(file, f"{tag} {name}", "identical duplicate ignored")
                else:
                    self.issue(
                        file,
                        f"{tag} {name}",
                        f"duplicate of the definition in {table[name][0]}; first one kept",
                    )
                continue
            table[name] = (file, elem)

    def _check_attrs(self, file: str, elem: ET.Element) -> None:
        """Report attributes the converter does not understand.

        Args:
            file: Source file name.
            elem: Element to inspect.

        Returns:
            None.

        Raises:
            None.
        """
        allowed = _ALLOWED_ATTRS.get(_local(elem.tag), set())
        for attr in elem.attrib:
            if attr not in allowed:
                label = f"{_local(elem.tag)} {elem.get('name', '')}".strip()
                self.issue(file, label, f"attribute '{attr}' is not converted")

    def build_enums(self) -> None:
        """Create enumerations from element rules and top-level conditions.

        Returns:
            None.

        Raises:
            None.
        """
        for name, (file, elem) in self.rule_elems.items():
            members = self._rule_members(elem, Ctx(file, name))
            if members:
                self._add_enum(name, members, self._help(elem))
                self.rule_enum_names.add(name)
        for name, (file, elem) in self.cond_elems.items():
            members = self._condition_members(elem, Ctx(file, name))
            self._add_enum(name, members, self._help(elem))
        entity_rule = self.enums.get("entityType")
        if entity_rule:
            self.entity_types = {
                m if isinstance(m, str) else m["name"] for m in entity_rule["values"]
            }

    def _add_enum(
        self, name: str, members: list[str | dict[str, Any]], help_text: str | None
    ) -> None:
        """Add or extend an enumeration; the first definition of a member wins.

        Args:
            name: Enumeration name.
            members: Members as strings or objects.
            help_text: Optional help text.

        Returns:
            None.

        Raises:
            None.
        """
        enum = self.enums.setdefault(name, {"name": name, "values": []})
        _put(enum, "help", help_text)
        seen = {m if isinstance(m, str) else m["name"] for m in enum["values"]}
        for member in members:
            key = member if isinstance(member, str) else member["name"]
            if key not in seen:
                seen.add(key)
                enum["values"].append(member)

    # -- value helpers -------------------------------------------------------

    @staticmethod
    def _help(elem: ET.Element) -> str | None:
        """Read help from the ``help`` attribute or a ``helpText`` child.

        Args:
            elem: Source element.

        Returns:
            The help text or None.

        Raises:
            None.
        """
        attr = elem.get("help")
        if attr:
            return attr
        for child in elem:
            if _local(child.tag) == "helpText" and child.text and child.text.strip():
                return child.text.strip()
        return None

    def _member(
        self, ctx: Ctx, text: str, version: str | None, help_text: str | None
    ) -> str | dict[str, Any]:
        """Build an enum member.

        Args:
            ctx: Conversion context, for reporting.
            text: Member text; may be empty (the empty-string value).
            version: Version gate or None.
            help_text: Help or None.

        Returns:
            A plain string, or an object when a gate or help is present. The
            empty string is always a plain string because the registry needs
            a non-empty ``name`` in member objects; a gate or help on it is
            dropped and reported.

        Raises:
            None.
        """
        if not version and not help_text:
            return text
        if text == "":
            self.issue(
                ctx,
                ctx.path,
                "version/help on an empty <value> dropped; the empty-string member is ungated",
            )
            return text
        member: dict[str, Any] = {"name": text}
        _put(member, "version", version)
        _put(member, "help", help_text)
        return member

    def _value_children(self, elem: ET.Element, ctx: Ctx) -> list[str | dict[str, Any]]:
        """Read ``<value>`` children as enum members.

        Args:
            elem: Parent element.
            ctx: Conversion context.

        Returns:
            The members in order.

        Raises:
            None.
        """
        members: list[str | dict[str, Any]] = []
        for child in elem:
            if _local(child.tag) != "value":
                continue
            text = (child.text or "").strip()
            members.append(self._member(ctx, text, child.get("version"), child.get("help")))
        return members

    def _rule_members(self, elem: ET.Element, ctx: Ctx) -> list[str | dict[str, Any]]:
        """Members of an element rule from ``values`` and ``<value>`` children.

        Args:
            elem: The element rule or field.
            ctx: Conversion context.

        Returns:
            The members in order.

        Raises:
            None.
        """
        members: list[str | dict[str, Any]] = []
        attr = elem.get("values")
        if attr:
            members.extend(v.strip() for v in attr.split(",") if v.strip())
        members.extend(self._value_children(elem, ctx))
        return members

    def _condition_values(
        self, cond: ET.Element, ctx: Ctx
    ) -> list[tuple[str, str | None, str | None]]:
        """Values selected by one ``<condition>``.

        Args:
            cond: The condition element.
            ctx: Conversion context.

        Returns:
            Tuples of (value, version, help).

        Raises:
            None.
        """
        cond_version = cond.get("version")
        values: list[tuple[str, str | None, str | None]] = []
        attr = cond.get("value")
        if attr is not None:
            values.append((attr.strip(), cond_version, None))
        for child in cond:
            if _local(child.tag) == "value":
                text = (child.text or "").strip()
                values.append((text, child.get("version") or cond_version, child.get("help")))
        if not values:
            self.issue(ctx, ctx.path, "<condition> without a value skipped")
        elif all(v[0] == "" for v in values):
            self.notice(ctx, ctx.path, "<condition> selects only the empty string")
        return values

    def _condition_members(self, elem: ET.Element, ctx: Ctx) -> list[str | dict[str, Any]]:
        """Selector enumeration members of a ``condition_field``.

        Args:
            elem: The condition field.
            ctx: Conversion context.

        Returns:
            The members in declaration order.

        Raises:
            None.
        """
        members: list[str | dict[str, Any]] = []
        for cond in elem:
            if _local(cond.tag) != "condition":
                continue
            members.extend(self._member(ctx, *v) for v in self._condition_values(cond, ctx))
        return members

    def _unique(self, used: set[str], base: str) -> str:
        """Return ``base`` or ``base#N`` so that it is not yet in ``used``.

        Args:
            used: Names already taken (updated).
            base: Preferred name.

        Returns:
            A unique name.

        Raises:
            None.
        """
        name = base
        counter = 2
        while name in used:
            name = f"{base}#{counter}"
            counter += 1
        used.add(name)
        return name

    def _hoist_enum(self, base: str, members: list[str | dict[str, Any]]) -> str:
        """Register a hoisted enumeration.

        Args:
            base: Preferred name.
            members: Enum members.

        Returns:
            The registered name.

        Raises:
            None.
        """
        taken = self._used_enums | set(self.enums)
        name = self._unique(taken, base)
        self._used_enums.add(name)
        self.enums[name] = {"name": name, "values": members}
        return name

    # -- node conversion -----------------------------------------------------

    def _common(self, elem: ET.Element, ctx: Ctx, node: dict[str, Any]) -> None:
        """Copy ``required``, ``version`` and ``help`` into a node.

        Args:
            elem: Source element.
            ctx: Conversion context.
            node: Destination node.

        Returns:
            None.

        Raises:
            None.
        """
        required = elem.get("required")
        if required is not None:
            low = required.strip().lower()
            if low in ("true", "false"):
                _put(node, "required", low == "true")
            else:
                self.issue(ctx, f"{ctx.path}.{elem.get('name')}", f"invalid required '{required}'")
        _put(node, "version", elem.get("version"))
        _put(node, "help", self._help(elem))

    def nodes(self, parent: ET.Element, ctx: Ctx) -> list[dict[str, Any]]:
        """Convert the node children of an element.

        Args:
            parent: Element whose children are converted.
            ctx: Conversion context.

        Returns:
            The converted nodes in order.

        Raises:
            None.
        """
        out: list[dict[str, Any]] = []
        for child in parent:
            tag = _local(child.tag)
            if tag in ("helpText", "value", ""):
                continue
            node = self.node(child, ctx)
            if node is not None:
                out.append(node)
        return out

    def node(self, elem: ET.Element, ctx: Ctx) -> dict[str, Any] | None:
        """Convert one node element.

        Args:
            elem: Source element.
            ctx: Conversion context.

        Returns:
            The JSON node, or None when it cannot be converted.

        Raises:
            None.
        """
        tag = _local(elem.tag)
        name = elem.get("name")
        if tag not in _ALLOWED_ATTRS or tag == "condition":
            self.issue(ctx, f"{ctx.path}.{tag}", "unsupported element skipped")
            return None
        if not name:
            self.issue(ctx, f"{ctx.path}.{tag}", "element without a name skipped")
            return None
        self._check_attrs(ctx.file, elem)
        if tag == "field":
            return self._field(elem, name, ctx)
        if tag == "structure_reference":
            node: dict[str, Any] = {
                "node": "structure_reference",
                "name": name,
                "structure": elem.get("type") or name,
            }
            self._common(elem, ctx, node)
            return node
        if tag == "structure":
            return self._nested_structure(elem, name, ctx)
        if tag == "iterative_field":
            return self._iterative(elem, name, ctx)
        if tag == "condition_field":
            return self._condition_field(elem, name, ctx)
        self.issue(ctx, f"{ctx.path}.{name}", f"'{tag}' is not used by the bundled Definitions")
        return None

    def _expand_condition(
        self, key: str, name: str, elem: ET.Element, ctx: Ctx
    ) -> dict[str, Any] | None:
        """Expand a reference to a top-level condition field inline.

        Args:
            key: Name of the top-level condition field.
            name: Key name of the referencing node.
            elem: The referencing element, for required/version/help.
            ctx: Conversion context.

        Returns:
            A ``condition_field`` node, or None on a reference cycle.

        Raises:
            None.
        """
        branches = self.cond_branches(key)
        if branches is None:
            self.issue(ctx, f"{ctx.path}.{name}", f"recursive condition '{key}' not expanded")
            return None
        node: dict[str, Any] = {
            "node": "condition_field",
            "name": name,
            "type": key,
            "branches": copy.deepcopy(branches),
        }
        self._common(elem, ctx, node)
        return node

    def _field(self, elem: ET.Element, name: str, ctx: Ctx) -> dict[str, Any] | None:
        """Convert a ``field`` element.

        Args:
            elem: The field element.
            name: Field name.
            ctx: Conversion context.

        Returns:
            A ``field`` node or an expanded ``condition_field`` node.

        Raises:
            None.
        """
        type_ = elem.get("type")
        validation = elem.get("validation")
        members = self._rule_members(elem, ctx.child(name))
        if type_ and type_ in self.cond_elems:
            return self._expand_condition(type_, name, elem, ctx)
        if not type_ and not validation and not members and name in self.cond_elems:
            return self._expand_condition(name, name, elem, ctx)
        node: dict[str, Any] = {"node": "field", "name": name}
        self._common(elem, ctx, node)
        _put(node, "type", type_)
        _put(node, "validation", validation)
        if members:
            if all(isinstance(m, str) for m in members):
                node["values"] = list(members)  # type: ignore[arg-type]
            else:
                node["type"] = self._hoist_enum(f"{ctx.path}.{name}", members)
        elif not type_ and not validation and name in self.rule_enum_names:
            node["type"] = name
        _put(node, "constraint", elem.get("constraint"))
        return node

    def _nested_structure(self, elem: ET.Element, name: str, ctx: Ctx) -> dict[str, Any]:
        """Hoist a nested ``structure`` and return a reference to it.

        Args:
            elem: The nested structure element.
            name: Its key name.
            ctx: Conversion context.

        Returns:
            A ``structure_reference`` node.

        Raises:
            None.
        """
        hoisted_name = self._hoist_structure(elem, name, ctx)
        node: dict[str, Any] = {
            "node": "structure_reference",
            "name": name,
            "structure": hoisted_name,
        }
        self._common(elem, ctx, node)
        return node

    def _hoist_structure(self, elem: ET.Element, name: str, ctx: Ctx) -> str:
        """Convert a nested structure into its own structure entry.

        Args:
            elem: The nested structure element.
            name: Its key name.
            ctx: Conversion context.

        Returns:
            The unique hoisted structure name.

        Raises:
            None.
        """
        taken = self._used_structs | set(self.struct_elems)
        hoisted_name = self._unique(taken, f"{ctx.path}.{name}")
        self._used_structs.add(hoisted_name)
        child_ctx = Ctx(ctx.file, hoisted_name)
        entry: dict[str, Any] = {"name": hoisted_name}
        _put(entry, "help", self._help(elem))
        entry["children"] = self.nodes(elem, child_ctx)
        self._hoisted.append((ctx.file, entry))
        return hoisted_name

    def _iterative(self, elem: ET.Element, count_key: str, ctx: Ctx) -> dict[str, Any]:
        """Convert an ``iterative_field``.

        Args:
            elem: The iterative field element.
            count_key: Name of the count key (the element's ``name``).
            ctx: Conversion context.

        Returns:
            An ``iterative_field`` node.

        Raises:
            None.
        """
        node: dict[str, Any] = {"node": "iterative_field", "name": count_key}
        node["count_key"] = count_key
        self._common(elem, ctx, node)
        limit = elem.get("limit")
        if limit is not None:
            try:
                node["limit"] = int(limit)
            except ValueError:
                self.issue(ctx, f"{ctx.path}.{count_key}", f"invalid limit '{limit}'")
        kids = [k for k in elem if _local(k.tag) not in ("helpText", "")]
        inner = Ctx(ctx.file, f"{ctx.path}.{count_key}")
        if not kids:
            self.notice(ctx, f"{ctx.path}.{count_key}", "iterative_field without children")
            node["name"] = _strip_count(count_key)
            return node
        if len(kids) > 1:
            node["name"] = _strip_count(count_key)
            node["children"] = self.nodes(elem, inner)
            self.notice(
                ctx,
                f"{ctx.path}.{count_key}",
                "iterative_field with several children converted to one block "
                f"named '{node['name']}'; confirm against the game format",
            )
            return node
        kid = kids[0]
        tag = _local(kid.tag)
        kid_name = kid.get("name") or _strip_count(count_key)
        node["name"] = kid_name
        if tag == "field":
            converted = self._field(kid, kid_name, inner)
            if converted is None or converted["node"] != "field":
                node["children"] = [converted] if converted else []
                return node
            for key in ("type", "validation"):
                _put(node, key, converted.get(key))
            if "values" in converted:
                node["type"] = self._hoist_enum(f"{inner.path}.{kid_name}", converted["values"])
            for key in ("version", "help"):
                if key not in node and key in converted:
                    node[key] = converted[key]
            if "constraint" in converted:
                self.notice(ctx, f"{ctx.path}.{count_key}", "constraint on repeated value dropped")
            return node
        if tag == "structure_reference":
            target = kid.get("type") or kid_name
            body = self._structure_body(target)
            if body is not None:
                self._inlined.add(target)
                node["children"] = body
            else:
                self.notice(
                    ctx,
                    f"{ctx.path}.{count_key}",
                    f"structure '{target}' not inlined; kept as a nested reference",
                )
                node["children"] = [
                    {"node": "structure_reference", "name": kid_name, "structure": target}
                ]
            for key in ("version", "help"):
                if key not in node and kid.get(key):
                    node[key] = kid.get(key)
            return node
        if tag == "structure":
            node["children"] = self.nodes(kid, Ctx(ctx.file, f"{inner.path}.{kid_name}"))
            for key in ("version", "help"):
                if key not in node and kid.get(key):
                    node[key] = kid.get(key)
            return node
        converted_kid = self.node(kid, inner)
        node["children"] = [converted_kid] if converted_kid else []
        return node

    def _condition_field(self, elem: ET.Element, name: str, ctx: Ctx) -> dict[str, Any] | None:
        """Convert an inline ``condition_field``.

        Args:
            elem: The condition field element.
            name: Selector key name.
            ctx: Conversion context.

        Returns:
            A ``condition_field`` node.

        Raises:
            None.
        """
        has_conditions = any(_local(c.tag) == "condition" for c in elem)
        if not has_conditions and name in self.cond_elems:
            return self._expand_condition(name, name, elem, ctx)
        node: dict[str, Any] = {"node": "condition_field", "name": name}
        self._common(elem, ctx, node)
        branches = self._branches(elem, ctx.child(name))
        members = self._condition_members(elem, ctx.child(name))
        names = {m if isinstance(m, str) else m["name"] for m in members}
        declared = elem.get("type")
        if declared and declared in self.enums:
            node["type"] = declared
        elif name in self.enums:
            node["type"] = name
        elif names and names <= {"TRUE", "FALSE"}:
            node["validation"] = "Boolean"
        else:
            node["type"] = self._hoist_enum(f"{ctx.path}.{name}", members)
        node["branches"] = branches
        return node

    def _branches(self, elem: ET.Element, ctx: Ctx) -> dict[str, list[dict[str, Any]]]:
        """Convert the ``<condition>`` children of a condition field.

        Args:
            elem: The condition field element.
            ctx: Conversion context (its path names hoisted structures).

        Returns:
            Branch nodes keyed by selector value.

        Raises:
            None.
        """
        branches: dict[str, list[dict[str, Any]]] = {}
        defined_at: dict[str, int] = {}
        ordinal = 0
        for cond in elem:
            if _local(cond.tag) != "condition":
                continue
            ordinal += 1
            self._check_attrs(ctx.file, cond)
            values = self._condition_values(cond, ctx)
            body = self.nodes(cond, ctx)
            for value, _version, _help in values:
                if value in branches and defined_at[value] != ordinal:
                    self.notice(
                        ctx,
                        f"{ctx.path}={value!r}",
                        f"value defined by <condition> #{defined_at[value]} and "
                        f"<condition> #{ordinal}; later definition (#{ordinal}) kept, "
                        f"earlier (#{defined_at[value]}) replaced",
                    )
                branches[value] = copy.deepcopy(body)
                defined_at[value] = ordinal
        return branches

    def cond_branches(self, key: str) -> dict[str, list[dict[str, Any]]] | None:
        """Branches of a top-level condition field, converted once.

        Args:
            key: Top-level condition field name.

        Returns:
            The branches, or None when ``key`` is being converted already.

        Raises:
            None.
        """
        if key in self._cond_branches:
            return self._cond_branches[key]
        marker = f"cond:{key}"
        if marker in self._in_progress:
            return None
        file, elem = self.cond_elems[key]
        self._in_progress.add(marker)
        try:
            result = self._branches(elem, Ctx(file, key))
        finally:
            self._in_progress.discard(marker)
        self._cond_branches[key] = result
        return result

    # -- structures and rules ------------------------------------------------

    def root_structure(self, name: str) -> dict[str, Any] | None:
        """Convert a top-level structure once.

        Args:
            name: Structure name.

        Returns:
            The structure entry, or None when unknown or being converted.

        Raises:
            None.
        """
        if name in self._roots:
            return self._roots[name]
        marker = f"struct:{name}"
        if marker in self._in_progress or name not in self.struct_elems:
            return None
        file, elem = self.struct_elems[name]
        self._in_progress.add(marker)
        try:
            entry: dict[str, Any] = {"name": name}
            ext = ROOT_EXTENSIONS.get(name)
            _put(entry, "extension", ext)
            _put(entry, "version", elem.get("version"))
            _put(entry, "help", self._help(elem))
            entry["children"] = self.nodes(elem, Ctx(file, name))
        finally:
            self._in_progress.discard(marker)
        self._roots[name] = entry
        self._root_file[name] = file
        return entry

    def _structure_body(self, name: str) -> list[dict[str, Any]] | None:
        """Copy of the child nodes of a top-level structure.

        Args:
            name: Structure name.

        Returns:
            Deep-copied children, or None when unavailable.

        Raises:
            None.
        """
        entry = self.root_structure(name)
        if entry is None:
            return None
        return copy.deepcopy(entry["children"])

    def _element_rule(self, name: str, file: str, elem: ET.Element) -> dict[str, Any]:
        """Convert a top-level ``element_rule``.

        Args:
            name: Rule name.
            file: Source file.
            elem: The element.

        Returns:
            The element rule entry.

        Raises:
            None.
        """
        rule: dict[str, Any] = {"name": name}
        _put(rule, "validation", elem.get("validation"))
        if name in self.rule_enum_names:
            rule["type"] = name
        elif elem.get("type"):
            rule["type"] = elem.get("type")
        _put(rule, "version", elem.get("version"))
        _put(rule, "help", self._help(elem))
        _put(rule, "constraint", elem.get("constraint"))
        return rule

    def convert(self) -> ConversionResult:
        """Convert everything that was loaded.

        Returns:
            The output documents and the report.

        Raises:
            None.
        """
        self.build_enums()
        for name in self.struct_elems:
            self.root_structure(name)
        for key in self.cond_elems:
            self.cond_branches(key)

        files: dict[str, dict[str, Any]] = {}

        def doc(source: str) -> dict[str, Any]:
            out_name = _output_name(source)
            return files.setdefault(out_name, {"schema": SCHEMA_VERSION, "structures": []})

        for source in self.file_order:
            for name, (file, _elem) in self.struct_elems.items():
                if file == source:
                    doc(source)["structures"].append(self._roots[name])
            for name, (file, elem) in self.rule_elems.items():
                if file == source:
                    doc(source).setdefault("element_rules", []).append(
                        self._element_rule(name, file, elem)
                    )
        for source, entry in self._hoisted:
            doc(source)["structures"].append(entry)
        files = {k: v for k, v in files.items() if v["structures"] or v.get("element_rules")}
        for document in files.values():
            document.setdefault("element_rules", [])
        files["enums.json"] = {"schema": SCHEMA_VERSION, "enums": list(self.enums.values())}
        self._final_checks(files)
        return ConversionResult(files, self.report)

    def _final_checks(self, files: dict[str, dict[str, Any]]) -> None:
        """Report dangling references and structures with no way in.

        Args:
            files: The converted documents.

        Returns:
            None.

        Raises:
            None.
        """
        known: dict[str, str] = {}
        for fname, document in files.items():
            for struct in document.get("structures", []):
                known.setdefault(struct["name"], fname)
        referenced: set[str] = set()

        def walk(nodes: list[dict[str, Any]], owner: str, fname: str) -> None:
            for node in nodes:
                kind = node.get("node")
                if kind == "structure_reference":
                    referenced.add(node["structure"])
                    if node["structure"] not in known:
                        self.issue(
                            fname,
                            f"{owner}.{node['name']}",
                            f"reference to unknown structure '{node['structure']}'",
                        )
                walk(node.get("children", []), owner, fname)
                for branch in (node.get("branches") or {}).values():
                    walk(branch, owner, fname)

        for fname, document in files.items():
            for struct in document.get("structures", []):
                walk(struct["children"], struct["name"], fname)
        for name in self.struct_elems:
            if (
                name in referenced
                or name in self._inlined
                or name in self.entity_types
                or name in ROOT_EXTENSIONS
            ):
                continue
            self.notice(
                self._root_file[name],
                f"structure {name}",
                "not an entityType, not referenced and not mapped to a file extension",
            )


def _strip_count(name: str) -> str:
    """Derive a repeated key name from a count key name.

    Args:
        name: Count key name, for example ``stageCount``.

    Returns:
        The name without a trailing ``Count`` (or ``Num`` prefix) when possible.

    Raises:
        None.
    """
    for suffix in ("Count", "count"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    if name.startswith("Num") and len(name) > 3:
        return name[3:]
    if name.startswith("num") and len(name) > 3 and name[3].isupper():
        return name[3].lower() + name[4:]
    return name


def _output_name(source: str) -> str:
    """Map an XML file name to its JSON output name.

    Args:
        source: XML file name.

    Returns:
        The JSON file name.

    Raises:
        None.
    """
    stem = Path(source).stem
    if stem.lower() in RESERVED_STEMS:
        stem = f"defs_{stem}"
    return f"{stem}.json"


def convert_texts(files: dict[str, str]) -> ConversionResult:
    """Convert XML Definition texts.

    Args:
        files: XML file name mapped to its text.

    Returns:
        The converted documents and the report.

    Raises:
        None. Problems are listed in the report.
    """
    converter = Converter()
    for name in sorted(files):
        converter.load_text(name, files[name])
    return converter.convert()


def convert_directory(xml_dir: Path) -> ConversionResult:
    """Convert all ``*.xml`` files in a directory.

    Args:
        xml_dir: Directory containing the XML Definitions.

    Returns:
        The converted documents and the report.

    Raises:
        OSError: If the directory cannot be read.
    """
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(xml_dir.glob("*.xml"))}
    return convert_texts(texts)


def write_result(result: ConversionResult, output: Path) -> list[Path]:
    """Write converted documents as JSON.

    Args:
        result: Conversion result.
        output: Destination directory (created when missing).

    Returns:
        The written paths.

    Raises:
        OSError: If a file cannot be written.
    """
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, document in sorted(result.files.items()):
        path = output / name
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _audit_correction_count(output: Path) -> int:
    """Count the audit corrections recorded beside an output directory.

    Args:
        output: Intended output directory.

    Returns:
        The number of ``audit_corrections`` in ``<output>/PROVENANCE.json``,
        or 0 when the file is absent or unreadable.

    Raises:
        None.
    """
    path = output / "PROVENANCE.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return 0
    corrections = data.get("audit_corrections") if isinstance(data, dict) else None
    return len(corrections) if isinstance(corrections, list) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the converter from the command line.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success, 1 with ``--strict`` when elements
        could not be converted, 2 on usage or I/O errors or when the output
        directory records audit corrections and ``--overwrite-corrections``
        was not given.

    Raises:
        None.
    """
    default_out = Path(__file__).resolve().parents[1] / "src" / "soase_validator" / "definitions"
    parser = argparse.ArgumentParser(description="Convert XML Definitions to bundled JSON.")
    parser.add_argument("xml_dir", type=Path, help="directory containing the XML Definition files")
    parser.add_argument("--output", type=Path, default=default_out, help="output directory")
    parser.add_argument("--strict", action="store_true", help="exit 1 when anything is unconverted")
    parser.add_argument(
        "--overwrite-corrections",
        action="store_true",
        help="write even when the output directory's PROVENANCE.json lists audit corrections "
        "(the conversion drops them; re-apply each one afterwards)",
    )
    args = parser.parse_args(argv)
    if not args.xml_dir.is_dir():
        print(f"error: {args.xml_dir} is not a directory", file=sys.stderr)
        return 2
    count = _audit_correction_count(args.output)
    if count and not args.overwrite_corrections:
        print(
            f"error: refusing to write to {args.output}: its PROVENANCE.json lists {count} "
            "audit correction(s) that converting from XML would drop. Definition corrections "
            "are made in the bundled JSON, not by re-running the converter. Pass "
            "--overwrite-corrections to overwrite anyway and re-apply them by hand.",
            file=sys.stderr,
        )
        return 2
    try:
        result = convert_directory(args.xml_dir)
        written = write_result(result, args.output)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = result.report
    print(f"Wrote {len(written)} files to {args.output}")
    print(f"Skipped non-Definition files: {', '.join(report.skipped_files) or 'none'}")
    print(f"Unconverted elements: {len(report.unconverted)}")
    for line in report.unconverted:
        print(f"  ! {line}")
    print(f"Notices: {len(report.notices)}")
    for line in report.notices:
        print(f"  - {line}")
    return 1 if args.strict and report.unconverted else 0


if __name__ == "__main__":
    sys.exit(main())
