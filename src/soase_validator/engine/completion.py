"""Completion, hover and go-to-definition.

The functions locate a position in a tolerant :class:`ParsedFile`, find the
Definition block that encloses it and answer from the Definitions and the
:class:`ChainIndex`. They are UI-agnostic: positions are zero-based and the
results are the model types from :mod:`soase_validator.engine.model`.

The line under the cursor is read from the text, not from the tree, because a
half-typed line is skipped by the parser. The tree supplies the enclosing
blocks and the sibling keys.

Key completions list the keys of the enclosing structure that are not yet
present. When a ``condition_field`` selector is set, only the selected branch
contributes. Value completions list the members of an enumeration for the
file's version, ``TRUE`` and ``FALSE`` for a Boolean, the ``entityType``
values for the version, and for a reference field the names of the Chain,
each once with the Layer that provides it in ``detail``. Kinds that name
files have no name list, so they give no value completions.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from soase_validator.engine.chainindex import ChainIndex, Resolution
from soase_validator.engine.model import (
    CompletionItem,
    FieldHelp,
    HoverResult,
    Location,
    Position,
    Range,
    Span,
)
from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    Node,
    NumberValue,
    ParsedFile,
    StringValue,
    Value,
    parse,
)
from soase_validator.engine.registry import (
    ConditionFieldDef,
    ConditionReferenceDef,
    EnumDef,
    EnumValueDef,
    FieldDef,
    IterativeFieldDef,
    Registry,
    StructureDef,
    StructureReferenceDef,
)
from soase_validator.engine.registry import Node as DefNode
from soase_validator.engine.structure import Expander, place
from soase_validator.engine.validator import (
    ARCHIVE_VERSION_KEY,
    ENTITY_EXTENSION,
    ENTITY_TYPE_ENUM,
    ENTITY_TYPE_KEY,
    REFERENCE_KINDS,
)
from soase_validator.engine.versions import GameVersion, effective_version, gate_allows

KIND_KEY = "key"
KIND_ENUM = "enum"
KIND_REFERENCE = "reference"
KIND_ENTITY_TYPE = "entity_type"

_WS = " \t"
_BOOLEAN = "Boolean"
_BOOLEAN_MEMBERS = ("TRUE", "FALSE")


@dataclass(frozen=True, slots=True)
class AssistContext:
    """Everything the assistance functions need besides the text.

    Attributes:
        registry: Loaded Definitions.
        version: The Project's Game Version.
        file: Path of the edited file; its extension selects the root
            structure.
        chain: Merged lookup over the Chain, or None when no Chain is
            available; reference features are then silent.
    """

    registry: Registry
    version: GameVersion
    file: Path = field(default_factory=Path)
    chain: ChainIndex | None = None


@dataclass(frozen=True, slots=True)
class _Rule:
    """The value rule of a Definition node."""

    type: str | None
    validation: str | None
    values: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class _Line:
    """The cursor line split at the cursor.

    Attributes:
        is_key: True when the cursor is in the key.
        key: The key already typed (the whole key for a value position).
        prefix: The partial token typed so far, without a leading quote.
        indent: Indentation width of the line.
        open: False when the value is already complete or is not a single
            token, so nothing is offered.
    """

    is_key: bool
    key: str
    prefix: str
    indent: int
    open: bool = True


def _walk(nodes: Sequence[Node]) -> Iterator[Node]:
    """Yield nodes in document order.

    Args:
        nodes: Sibling nodes.

    Returns:
        An iterator over the nodes and all their descendants.
    """
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _scalar_text(value: Value | None) -> str | None:
    """Return the text a scalar value is matched by.

    Args:
        value: Parsed value or None.

    Returns:
        The quoted text, the ``TRUE``/``FALSE`` word or the raw token; None
        for a list or a missing value.
    """
    match value:
        case StringValue():
            return value.text
        case BoolValue():
            return "TRUE" if value.value else "FALSE"
        case NumberValue() | HexValue():
            return value.raw
        case _:
            return None


def _contains(span: Span | None, pos: Position) -> bool:
    """Tell whether a single-line span holds a position.

    Args:
        span: The span, or None.
        pos: The position.

    Returns:
        True when the position is on the span's line within its columns.
    """
    return (
        span is not None
        and span.line == span.end_line == pos.line
        and span.col <= pos.col < span.end_col
    )


def _split_line(text: str, pos: Position) -> _Line | None:
    """Read the cursor line up to the cursor.

    Args:
        text: Full document text.
        pos: The cursor.

    Returns:
        The split line, or None when the line cannot take a completion (a
        keyless row).
    """
    lines = text.split("\n")
    line = lines[pos.line].rstrip("\r") if 0 <= pos.line < len(lines) else ""
    before = line[: pos.col]
    body = before.lstrip(_WS)
    indent = len(before) - len(body)
    if not body:
        return _Line(True, "", "", pos.col)
    if body.startswith("["):
        return None
    key_end = next((i for i, ch in enumerate(body) if ch in _WS), None)
    if key_end is None:
        return _Line(True, body, body, indent)
    key = body[:key_end]
    rest = body[key_end:].lstrip(_WS)
    if rest.startswith("="):
        rest = rest[1:].lstrip(_WS)
    if rest.startswith('"'):
        rest = rest[1:]
        single = '"' not in rest
    else:
        single = not any(ch in _WS or ch in '"[' for ch in rest)
    return _Line(False, key, rest, indent, single)


def _file_version(parsed: ParsedFile, project: GameVersion) -> GameVersion:
    """Choose the version whose rules apply to the file.

    Args:
        parsed: The parsed file.
        project: The Project's Game Version.

    Returns:
        The version for the file's ``SinsArchiveVersion`` level, capped at
        the Project's version; the Project's version for a ``TXT`` file or
        an unusable level.
    """
    if parsed.header != "TXT2":
        return project
    node = next((n for n in parsed.nodes if n.key == ARCHIVE_VERSION_KEY), None)
    if node is None or not isinstance(node.value, NumberValue) or not node.value.is_integer:
        return project
    return effective_version(int(node.value.value), project)


class _View:
    """Definition lookups for one parsed file."""

    def __init__(self, ctx: AssistContext, parsed: ParsedFile) -> None:
        """Create a view.

        Args:
            ctx: The assistance context.
            parsed: The parsed file.
        """
        self.ctx = ctx
        self.registry = ctx.registry
        self.roots: Sequence[Node] = parsed.nodes
        self.version = _file_version(parsed, ctx.version)
        self._declared: dict[str, tuple[str, ...]] = {}
        step = self.root()
        if step is not None:
            expander = Expander(self.registry, self.allowed)
            header_keys = frozenset({ENTITY_TYPE_KEY, ARCHIVE_VERSION_KEY})
            self.roots = place(parsed.nodes, step[0], expander, header_keys).nodes

    def allowed(self, gate: str | None) -> bool:
        """Evaluate a version gate for the file's version.

        Args:
            gate: Gate expression or None.

        Returns:
            True when the element is defined for the file's version.
        """
        return gate_allows(gate, self.version)

    def enum_allows(self, enum: EnumDef, text: str) -> bool:
        """Tell whether a text is a member of an enumeration for the version.

        Args:
            enum: The enumeration.
            text: Candidate member.

        Returns:
            True when both the enumeration and the member are defined.
        """
        return self.allowed(enum.version) and any(
            m.name == text and self.allowed(m.version) for m in enum.values
        )

    def entity_structure(self, name: str) -> StructureDef | None:
        """Look up the root structure an ``entityType`` value selects.

        Args:
            name: The ``entityType`` text.

        Returns:
            The structure, or None when the value is not a member for the
            version or its structure is not defined for it.
        """
        enum = self.registry.enum(ENTITY_TYPE_ENUM)
        if enum is None or not self.enum_allows(enum, name):
            return None
        struct = self.registry.structure(name)
        return struct if struct is not None and self.allowed(struct.version) else None

    def entity_members(self) -> list[EnumValueDef]:
        """List the ``entityType`` members defined for the version.

        Returns:
            Enumeration members whose structure exists for the version, in
            declared order.
        """
        enum = self.registry.enum(ENTITY_TYPE_ENUM)
        if enum is None or not self.allowed(enum.version):
            return []
        return [m for m in enum.values if self.entity_structure(m.name) is not None]

    def root(self) -> tuple[Sequence[DefNode], str] | None:
        """Pick the root structure of the file.

        Returns:
            Its child Definitions and name, or None when the extension has
            no Definition or an ``.entity`` file has no usable ``entityType``.
        """
        ext = self.ctx.file.suffix.casefold()
        struct: StructureDef | None
        if ext == ENTITY_EXTENSION:
            node = next((n for n in self.roots if n.key == ENTITY_TYPE_KEY), None)
            text = (
                node.value.text if node is not None and isinstance(node.value, StringValue) else ""
            )
            struct = self.entity_structure(text) if text else None
        else:
            struct = self.registry.structure_for_extension(ext)
            if struct is not None and not self.allowed(struct.version):
                struct = None
        return (struct.children, struct.name) if struct is not None else None

    def expand(self, defs: Sequence[DefNode], siblings: Sequence[Node]) -> list[DefNode]:
        """Gate-filter Definitions and merge the selected condition branches.

        Args:
            defs: Definition nodes of the block.
            siblings: The block's file nodes, searched for each selector.

        Returns:
            The active nodes in declared order.
        """
        out: list[DefNode] = []
        for definition in defs:
            if not self.allowed(definition.version):
                continue
            if isinstance(definition, StructureReferenceDef):
                struct = self.registry.structure(definition.structure)
                if struct is not None and not self.allowed(struct.version):
                    continue
            out.append(definition)
            if isinstance(definition, ConditionFieldDef) and definition.branches:
                selector = next((n for n in siblings if n.key == definition.name), None)
                text = _scalar_text(selector.value) if selector is not None else None
                if text is not None and text in definition.branches:
                    out.extend(self.expand(definition.branches[text], siblings))
        return out

    def enter(
        self, active: Sequence[DefNode], node: Node, siblings: Sequence[Node]
    ) -> tuple[Sequence[DefNode], str] | None:
        """Find the Definitions that describe a block node.

        Args:
            active: Active Definitions of the block that holds the node.
            node: The block node.
            siblings: The nodes next to it.

        Returns:
            The child Definitions and a name for the block, or None when the
            node is not a described block.
        """
        for definition in active:
            if definition.name != node.key:
                continue
            target: str | None = None
            if isinstance(definition, IterativeFieldDef):
                if definition.children:
                    return definition.children, definition.name
                continue
            if isinstance(definition, StructureReferenceDef):
                target = definition.structure
            elif isinstance(definition, ConditionReferenceDef):
                selector = next((n for n in siblings if n.key == definition.selector), None)
                text = _scalar_text(selector.value) if selector is not None else None
                target = definition.cases.get(text) if text is not None else None
            struct = self.registry.structure(target) if target else None
            if struct is None or not self.allowed(struct.version):
                return None
            return struct.children, struct.name
        return None

    def block_at(self, ancestors: Sequence[Node]) -> tuple[Sequence[DefNode], str] | None:
        """Find the Definitions of the block inside a chain of ancestors.

        Args:
            ancestors: Block nodes from the outermost inward.

        Returns:
            The child Definitions and name of the innermost block, or None
            when any step is not described.
        """
        step = self.root()
        siblings: Sequence[Node] = self.roots
        for ancestor in ancestors:
            if step is None:
                return None
            step = self.enter(self.expand(step[0], siblings), ancestor, siblings)
            siblings = ancestor.children
        return step

    def declared_values(self, path: str) -> tuple[str, ...]:
        """Collect the string values a key path names anywhere in the file.

        Args:
            path: Dotted key path such as ``player.designName``.

        Returns:
            The quoted values in file order.
        """
        cached = self._declared.get(path)
        if cached is None:
            level: Sequence[Node] = self.roots
            *blocks, leaf = path.split(".")
            for key in blocks:
                level = [child for node in level if node.key == key for child in node.children]
            cached = tuple(
                node.value.text
                for node in level
                if node.key == leaf and isinstance(node.value, StringValue)
            )
            self._declared[path] = cached
        return cached

    def rule(self, definition: DefNode, key: str) -> _Rule | None:
        """Build the value rule of a Definition node for a key.

        Args:
            definition: The matching Definition node.
            key: The key as written.

        Returns:
            The rule, or None when the key holds no checked value (a block,
            or a count line).
        """
        if isinstance(definition, FieldDef):
            if not (definition.type or definition.validation or definition.values):
                shared = self.registry.element_rule(definition.name)
                if shared is not None:
                    return _Rule(shared.type, shared.validation, shared.values)
            values = definition.values
            if definition.values_from is not None:
                values = (*(values or ()), *self.declared_values(definition.values_from))
            return _Rule(definition.type, definition.validation, values)
        if isinstance(definition, ConditionFieldDef):
            return _Rule(definition.type, definition.validation, None)
        if (
            isinstance(definition, IterativeFieldDef)
            and key == definition.name
            and not definition.children
        ):
            return _Rule(definition.type, definition.validation, None)
        return None


def _find_definition(active: Sequence[DefNode], key: str) -> DefNode | None:
    """Find the Definition node a key belongs to.

    Count lines take precedence, as in validation.

    Args:
        active: Active Definition nodes of the block.
        key: The key as written.

    Returns:
        The node, or None for an undefined key.
    """
    for definition in active:
        if isinstance(definition, IterativeFieldDef) and key == definition.count_key:
            return definition
    for definition in active:
        if definition.name == key:
            return definition
    return None


def _validation_type(definition: DefNode, key: str) -> str:
    """Describe the validation type of a Definition node.

    Args:
        definition: The node.
        key: The key as written; separates a count line from its repeats.

    Returns:
        A short type description.
    """
    match definition:
        case FieldDef() | ConditionFieldDef():
            return definition.validation or definition.type or "Enum"
        case IterativeFieldDef():
            if key == definition.count_key:
                return f"Count of {definition.name}"
            return definition.validation or definition.type or "Block"
        case StructureReferenceDef():
            return f"Block ({definition.structure})"
        case ConditionReferenceDef():
            return f"Block (by {definition.selector})"
    return ""


def _key_name(definition: DefNode, key: str | None = None) -> str:
    """Return the key a Definition node is written with.

    Args:
        definition: The node.
        key: The key already known to be written, if any.

    Returns:
        The count key for an iterative field, else the node name.
    """
    if key is not None:
        return key
    return definition.count_key if isinstance(definition, IterativeFieldDef) else definition.name


def _field_help(structure: str, definition: DefNode, key: str) -> FieldHelp:
    """Build the help of a Definition node.

    Args:
        structure: Name of the structure the node belongs to.
        definition: The node.
        key: The key as written.

    Returns:
        The field help.
    """
    return FieldHelp(
        structure=structure,
        field=key,
        validation_type=_validation_type(definition, key),
        required=definition.required,
        help=definition.help,
        version_gate=definition.version,
    )


def _hover_text(info: FieldHelp) -> str:
    """Format field help as Markdown.

    Args:
        info: The field help.

    Returns:
        Markdown with the help text, validation type, required status and
        version gate.
    """
    lines = [f"**{info.field}**"]
    if info.help:
        lines += ["", info.help]
    lines += [
        "",
        f"- Type: {info.validation_type}",
        f"- Required: {'yes' if info.required else 'no'}",
    ]
    if info.version_gate:
        lines.append(f"- Version: {info.version_gate}")
    return "\n".join(lines)


def _matches(label: str, prefix: str) -> bool:
    """Tell whether a label starts with a prefix, ignoring case.

    Args:
        label: Candidate text.
        prefix: What the user typed.

    Returns:
        True when the label matches.
    """
    return label.casefold().startswith(prefix.casefold())


def _ancestors(roots: Sequence[Node], line: int, indent: int) -> list[Node]:
    """Find the block nodes that enclose a new line.

    The nodes are the placed tree. A line already in the tree belongs to the
    block it was placed in. A line without a node (an empty line) joins the
    block of the last earlier line when it is indented deeper than that block.

    Args:
        roots: Top-level nodes of the placed tree.
        line: Zero-based line of the cursor.
        indent: Indentation width of the cursor line.

    Returns:
        Enclosing block nodes, outermost first.
    """
    previous: Node | None = None
    for node in _walk(roots):
        if node.key_span.line == line:
            return _parents(node)
        if node.key_span.line < line and (
            previous is None or node.key_span.line > previous.key_span.line
        ):
            previous = node
    if previous is None:
        return []
    chain = _parents(previous)
    if previous.value is None:
        chain.append(previous)
    while chain and chain[-1].indent >= indent:
        chain.pop()
    return chain


def _parents(node: Node) -> list[Node]:
    """List the enclosing blocks of a node.

    Args:
        node: A parsed node.

    Returns:
        Its ancestors, outermost first.
    """
    chain: list[Node] = []
    parent = node.parent
    while parent is not None:
        chain.append(parent)
        parent = parent.parent
    chain.reverse()
    return chain


def _reference_items(ctx: AssistContext, kind: str) -> list[CompletionItem]:
    """List the names of a reference kind.

    Args:
        ctx: The assistance context.
        kind: Reference kind.

    Returns:
        One item per name with the providing Layer in ``detail``; empty
        without a Chain or for a kind that names files.
    """
    if ctx.chain is None:
        return []
    return [
        CompletionItem(res.entry.name, KIND_REFERENCE, res.layer.name)
        for res in ctx.chain.names(kind)
    ]


def _value_items(view: _View, rule: _Rule, key: str) -> list[CompletionItem]:
    """List the valid values for a rule.

    Args:
        view: The file view.
        rule: The value rule of the field.
        key: The key as written.

    Returns:
        Unfiltered candidates.
    """
    if rule.values is not None:
        return [CompletionItem(v, KIND_ENUM) for v in rule.values]
    enum = view.registry.enum(rule.type) if rule.type else None
    if enum is not None:
        if not view.allowed(enum.version):
            return []
        return [
            CompletionItem(m.name, KIND_ENUM, documentation=m.help)
            for m in enum.values
            if view.allowed(m.version)
        ]
    validation = rule.validation or rule.type
    if validation == _BOOLEAN:
        return [CompletionItem(v, KIND_ENUM) for v in _BOOLEAN_MEMBERS]
    if validation in REFERENCE_KINDS:
        return _reference_items(view.ctx, validation or "")
    return []


def _key_items(
    view: _View, active: Sequence[DefNode], siblings: Sequence[Node]
) -> list[CompletionItem]:
    """List the keys of a block that are not yet present.

    Args:
        view: The file view.
        active: Active Definition nodes of the block.
        siblings: The block's file nodes without the cursor line.

    Returns:
        Unfiltered candidates, each key once, in declared order.
    """
    present = {n.key for n in siblings}
    items: list[CompletionItem] = []
    seen: set[str] = set()
    for definition in active:
        key = _key_name(definition)
        if key in present or key in seen:
            continue
        seen.add(key)
        items.append(
            CompletionItem(key, KIND_KEY, _validation_type(definition, key), definition.help)
        )
    return items


def complete(text: str, position: Position, ctx: AssistContext) -> list[CompletionItem]:
    """Compute completions at a position.

    Args:
        text: Full document text.
        position: Zero-based cursor position.
        ctx: The assistance context.

    Returns:
        Candidates filtered by the typed prefix, ignoring case. Empty when
        the file type has no Definition or the position takes no completion.

    Raises:
        None.
    """
    line = _split_line(text, position)
    if line is None or not line.open:
        return []
    parsed = parse(text, ctx.file, ctx.version)
    view = _View(ctx, parsed)
    ancestors = _ancestors(view.roots, position.line, line.indent)
    pool = ancestors[-1].children if ancestors else view.roots
    siblings = [n for n in pool if n.key_span.line != position.line]

    is_entity_root = ctx.file.suffix.casefold() == ENTITY_EXTENSION and not ancestors
    if not line.is_key and is_entity_root and line.key == ENTITY_TYPE_KEY:
        items = [
            CompletionItem(m.name, KIND_ENTITY_TYPE, documentation=m.help)
            for m in view.entity_members()
        ]
        return [i for i in items if _matches(i.label, line.prefix)]

    block = view.block_at(ancestors)
    items = []
    if line.is_key:
        if block is not None:
            items = _key_items(view, view.expand(block[0], siblings), siblings)
        if is_entity_root and not any(n.key == ENTITY_TYPE_KEY for n in siblings):
            items.insert(0, CompletionItem(ENTITY_TYPE_KEY, KIND_KEY, "entityType", None))
    elif block is not None:
        definition = _find_definition(view.expand(block[0], siblings), line.key)
        rule = view.rule(definition, line.key) if definition is not None else None
        if rule is not None:
            items = _value_items(view, rule, line.key)
    return [i for i in items if _matches(i.label, line.prefix)]


def _node_at(roots: Sequence[Node], pos: Position) -> tuple[Node, bool] | None:
    """Find the node whose key or value holds a position.

    Args:
        roots: Top-level nodes.
        pos: The position.

    Returns:
        The node and whether the position is on its value, or None.
    """
    for node in _walk(roots):
        if _contains(node.key_span, pos):
            return node, False
        if _contains(node.value_span, pos):
            return node, True
    return None


def _resolve_value(view: _View, node: Node, definition: DefNode) -> tuple[str, Resolution] | None:
    """Resolve the reference a value names.

    Args:
        view: The file view.
        node: The node whose value is hovered.
        definition: The node's Definition.

    Returns:
        The reference kind and the resolution, or None when the field is not
        a reference, no Chain is available or the name is not provided.
    """
    rule = view.rule(definition, node.key)
    chain = view.ctx.chain
    if rule is None or chain is None or rule.values is not None:
        return None
    if rule.type and view.registry.enum(rule.type) is not None:
        return None
    kind = rule.validation or rule.type or ""
    if kind not in REFERENCE_KINDS:
        return None
    if not isinstance(node.value, StringValue) or not node.value.text:
        return None
    found = chain.lookup(kind, node.value.text, view.ctx.file.suffix.casefold())
    return (kind, found) if found is not None else None


def _target(
    text: str, position: Position, ctx: AssistContext
) -> tuple[_View, Node, bool, DefNode, str] | None:
    """Find the node under a position and its Definition.

    Args:
        text: Full document text.
        position: Zero-based position.
        ctx: The assistance context.

    Returns:
        The view, node, whether the position is on the value, the Definition
        node and the name of the structure it belongs to; None for an
        undefined key or an undescribed block.
    """
    parsed = parse(text, ctx.file, ctx.version)
    view = _View(ctx, parsed)
    hit = _node_at(view.roots, position)
    if hit is None:
        return None
    node, on_value = hit
    block = view.block_at(_parents(node))
    if block is None:
        return None
    siblings = node.parent.children if node.parent is not None else view.roots
    definition = _find_definition(view.expand(block[0], siblings), node.key)
    if definition is None:
        return None
    return view, node, on_value, definition, block[1]


def hover(text: str, position: Position, ctx: AssistContext) -> HoverResult | None:
    """Compute hover content at a position.

    A key gives its help, validation type, required status and version gate.
    An enumeration value gives the member's help, if it has any. A reference
    value names the Layer that provides it and the lower Layer it overrides.

    Args:
        text: Full document text.
        position: Zero-based position.
        ctx: The assistance context.

    Returns:
        The hover content, or None for an undefined key or a value with
        nothing to say.

    Raises:
        None.
    """
    found = _target(text, position, ctx)
    if found is None:
        return None
    view, node, on_value, definition, structure = found
    if not on_value:
        info = _field_help(structure, definition, node.key)
        return HoverResult(_hover_text(info), node.key_span.to_range())
    span = node.value_span
    if span is None:
        return None
    resolved = _resolve_value(view, node, definition)
    if resolved is not None:
        kind, res = resolved
        body = f"{kind} `{res.entry.name}` is provided by Layer `{res.layer.name}`."
        if res.overrides is not None:
            body += f" It overrides the same name in Layer `{res.overrides.name}`."
        return HoverResult(body, span.to_range())
    rule = view.rule(definition, node.key)
    value = _scalar_text(node.value)
    enum = view.registry.enum(rule.type) if rule is not None and rule.type else None
    if rule is None or rule.values is not None or enum is None or value is None:
        return None
    member = next((m for m in enum.values if m.name == value and view.allowed(m.version)), None)
    if member is None or not member.help or not view.allowed(enum.version):
        return None
    return HoverResult(member.help, span.to_range())


def goto_definition(text: str, position: Position, ctx: AssistContext) -> Location | None:
    """Find the file that defines the reference under a position.

    Args:
        text: Full document text.
        position: Zero-based position.
        ctx: The assistance context.

    Returns:
        The file from the highest Layer that provides the name, at the start
        of the file; None when the position is not on a resolvable reference.

    Raises:
        None.
    """
    found = _target(text, position, ctx)
    if found is None:
        return None
    view, node, on_value, def_node, _ = found
    if not on_value:
        return None
    resolved = _resolve_value(view, node, def_node)
    if resolved is None:
        return None
    start = Position(0, 0)
    return Location(resolved[1].entry.file, Range(start, start))


def _flatten(defs: Sequence[DefNode]) -> Iterator[DefNode]:
    """Yield Definition nodes including those inside condition branches.

    Args:
        defs: Definition nodes.

    Returns:
        An iterator over the nodes and every branch node.
    """
    for definition_node in defs:
        yield definition_node
        if isinstance(definition_node, ConditionFieldDef) and definition_node.branches:
            for branch in definition_node.branches.values():
                yield from _flatten(branch)


def field_help(
    registry: Registry, structure: str, field_name: str, version: GameVersion
) -> FieldHelp | None:
    """Look up the help of a field of a structure.

    Args:
        registry: Loaded Definitions.
        structure: Structure name.
        field_name: Field key; the count key of an iterative field is accepted.
        version: Game Version; of several fields with the same name the one
            defined for it is preferred.

    Returns:
        The help, or None when the structure or the field is undefined.
    """
    struct = registry.structure(structure)
    if struct is None:
        return None
    matches = [
        d
        for d in _flatten(struct.children)
        if d.name == field_name or (isinstance(d, IterativeFieldDef) and d.count_key == field_name)
    ]
    if not matches:
        return None
    chosen = next((d for d in matches if gate_allows(d.version, version)), matches[0])
    return _field_help(structure, chosen, field_name)


def entity_types(registry: Registry, version: GameVersion) -> list[str]:
    """List the ``entityType`` values valid for a Game Version.

    Args:
        registry: Loaded Definitions.
        version: Game Version.

    Returns:
        The enumeration members whose structure is defined for the version,
        in declared order.
    """
    view = _View(AssistContext(registry, version), ParsedFile(None, [], []))
    return [m.name for m in view.entity_members()]


__all__ = [
    "KIND_ENTITY_TYPE",
    "KIND_ENUM",
    "KIND_KEY",
    "KIND_REFERENCE",
    "AssistContext",
    "complete",
    "entity_types",
    "field_help",
    "goto_definition",
    "hover",
]
