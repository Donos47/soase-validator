"""Structural and value validation of a parsed mod file.

``validate(parsed, ctx)`` is a pure function: it walks the parsed tree
against the Definitions in the Registry and returns Diagnostics. It does no
I/O, never writes to stdout and does not raise for malformed input. Parser
Diagnostics (``P`` family) stay in ``ParsedFile.diagnostics``; the caller
merges them.

Codes produced
--------------
``SOASE-V010``
    Unknown ``entityType`` for the active Game Version (on the value).
``SOASE-V020``
    Key not defined by the governing structure or selected branch (on the
    key). A key that exists only in a branch other than the selected one is
    reported the same way, with a hint naming that branch.
``SOASE-V030``
    Iterative count differs from the number of repeats, count over the
    ``limit``, or a repeat with no count line before it (on the count line,
    or the repeated key).
``SOASE-V040``
    Required field missing (on the key of the enclosing block, or the
    header line for the file root).
``SOASE-V050``
    Invalid value: a primitive checker failed, an enumeration value is not a
    member for the Game Version, or a block/value was found where the other
    was expected (on the value, or on the key when there is no value).
``SOASE-V060``
    Key out of the declared order of its block (on the key). The message
    names the in-order key it must come before or after.
``SOASE-V070``
    Plain key or count line used more than once in a block (on the repeated
    key); the message gives the line of the first use.
``SOASE-V080``
    Unexpected indentation (on the deeper line's key): a line deeper than
    the known value line before it, which is named as probably
    under-indented, or a counted repeat at another depth or in a style
    other than its run's first repeat.
``SOASE-R010``
    Reference value that the ``ReferenceLookup`` reports as not found (on
    the value). An ``Unknown`` result (incomplete Chain) reports nothing.

Walk rules
----------
* The root structure comes from the extension; for ``.entity`` it comes from
  the ``entityType`` value. The top-level ``entityType`` key and, in
  ``TXT2`` files, the top-level ``SinsArchiveVersion`` key are header keys
  that no root structure defines; they are not reported as unknown.
* A ``StructureCursor`` holds the gate-filtered, branch-expanded Definition
  nodes of one block, the keys seen so far and the lookup tables. A
  ``condition_field`` is a field plus a branch: the branch for the selector
  value is merged into the same block and the other branches are undefined.
* An ``iterative_field`` is a count line followed by that many repeats. The
  repeats are the consecutive siblings directly after the count line, so two
  iterative fields that repeat the same key name stay apart. A repeat is
  either a block named ``name`` (Definition children), a value line named
  ``name`` (no children), or, when the first child is the selector named
  like the iteration itself, a sequence of sibling lines (selector line then
  the selected branch's nodes, for example particle ``EmitterType`` plus
  ``EmitterContents``). Block extents come from indentation, never from the
  count.
* Order and duplicates: keys of a block must appear in the order the
  gate-filtered Definition declares them; optional keys may be absent. The
  selected ``condition_field`` branch counts as sitting right after the
  selector, and an iterative field's count line plus its run of repeats
  occupies the field's declared position. Plain keys and count lines may
  appear once per block; repeats inside a counted run are not duplicates.
  A duplicate takes no position (``SOASE-V070`` only), and an unknown key
  takes none either (``SOASE-V020`` only). Of the placed keys, a longest
  strictly increasing run of declared positions is "in order"; each other
  key gets one ``SOASE-V060``, so one misplaced key never blames the keys
  after it.
* Second ``buffType``: in an Ability block, the second ``buffType`` line
  after an ``aiUseTime`` line with the value
  ``OnlyWhenManyTargetsInCombatDoNotHaveBuff`` is the field that branch
  declares and is not a duplicate. A third ``buffType``, a second one before
  the ``aiUseTime`` line, or one under any other ``aiUseTime`` value stays
  ``SOASE-V070``.
* Declared values: a field with ``values_from`` (a dotted key path from
  the file root, for example ``player.designName``) accepts its ``values``
  plus every quoted value found at that path anywhere in the file, so a
  planet ``owner`` may name a player declared after the planets. Matching
  is case-sensitive. A file with no such values accepts only ``values``.
* Shallow members: a line with a value that follows a block repeat at the
  repeat's own indentation and is unknown to the enclosing block, but is a
  field of that repeat block, belongs to that repeat, together with the
  deeper lines after it (the galaxy planet ``owner`` shape). The repeat
  block validates them as its own members, so they give no unknown-key,
  count, order or duplicate findings. The shape is reported once, as
  ``SOASE-V080`` on the first deeper line after the shallow line. Any
  other unknown key keeps ``SOASE-V020``.
* Indentation: after the walk, every line deeper than the line before it
  is checked. A block header (no value) may be followed by a deeper line;
  so may a count line, by the first repeat of its run exactly one level
  deeper. Any other deeper line gets ``SOASE-V080`` when the previous line
  is known: matched in its block as a field, count line or repeat, or an
  unknown key that is a field of the repeat block ending right before it
  at the same indentation, when that repeat is not placed by a count line.
  Other unknown keys, repeats without a count line and lines inside
  unmatched blocks are skipped. The repeats of a run sit at the count
  line's level or one level deeper, one style per run. The pass leaves the
  tree and the other findings unchanged.

"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from soase_validator.engine.diagnostics import (
    CODE_CATALOGUE,
    R010,
    V010,
    V020,
    V030,
    V040,
    V050,
    V060,
    V070,
    V080,
)
from soase_validator.engine.model import Diagnostic, Severity, Span
from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    Node,
    NumberValue,
    ParsedFile,
    StringValue,
    Value,
)
from soase_validator.engine.primitives import (
    NumericPrefs,
    PrimitiveResult,
    check_any,
    check_boolean,
    check_color,
    check_coordinate,
    check_decimal,
    check_integer,
    check_orientation,
    check_position,
    validate_constraint,
)
from soase_validator.engine.registry import (
    ConditionFieldDef,
    ConditionReferenceDef,
    ElementRuleDef,
    EnumDef,
    FieldDef,
    IterativeFieldDef,
    LoadWarning,
    Registry,
    StructureDef,
    StructureReferenceDef,
)
from soase_validator.engine.registry import Node as DefNode
from soase_validator.engine.versions import (
    GameVersion,
    display_name,
    effective_version,
    gate_allows,
    introduced_in,
)

_LOG = logging.getLogger(__name__)

#: Validation types whose values are names resolved through a ReferenceLookup.
#: The kind passed to ``resolve`` is the validation type itself. These map
#: one to one onto the Reference Index kinds in design.md (entities, brushes,
#: string IDs, sounds, sound files, meshes, particles, explosions, galaxy
#: designs, galaxy templates, orbit body types).
REFERENCE_KINDS = frozenset(
    {
        "Entity",
        "Brush",
        "StringInfo",
        "Sound",
        "SoundFile",
        "Mesh",
        "Particle",
        "Explosion",
        "GalaxyDesign",
        "GalaxyTemplate",
        "GalaxyOrbitBodyType",
    }
)

#: Validation types holding a quoted name that has no Reference Index kind in
#: design.md. They are checked for shape only and never resolved.
UNRESOLVED_NAME_TYPES = frozenset({"Texture", "MeshPoint"})

#: Enumeration listing the ``entityType`` values.
ENTITY_TYPE_ENUM = "entityType"
ENTITY_TYPE_KEY = "entityType"
ARCHIVE_VERSION_KEY = "SinsArchiveVersion"
ENTITY_EXTENSION = ".entity"
AI_USE_TIME_BUFF_ROOT = "Ability"
AI_USE_TIME_BUFF_KEY = "buffType"
AI_USE_TIME_KEY = "aiUseTime"
AI_USE_TIME_BUFF_VALUE = "OnlyWhenManyTargetsInCombatDoNotHaveBuff"


@dataclass(frozen=True, slots=True)
class Found:
    """A reference that resolved.

    Attributes:
        detail: Optional payload (for example the providing Layer).
    """

    detail: object | None = None


@dataclass(frozen=True, slots=True)
class NotFound:
    """A reference that is absent from a complete Chain."""


@dataclass(frozen=True, slots=True)
class Unknown:
    """A reference that cannot be decided (incomplete Chain)."""


ResolveResult = Found | NotFound | Unknown


class ReferenceLookup(Protocol):
    """Resolves reference values to names in the Chain."""

    def resolve(self, kind: str, name: str) -> ResolveResult:
        """Resolve a reference.

        Args:
            kind: Reference kind, the validation type (for example ``Brush``).
            name: The referenced name; comparison is case-insensitive.

        Returns:
            ``Found``, ``NotFound`` or ``Unknown``.

        Raises:
            None.
        """
        ...


class NullReferenceLookup:
    """Lookup used when no Chain is available: every reference is unknown."""

    def resolve(self, kind: str, name: str) -> ResolveResult:
        """Return ``Unknown`` for every reference.

        Args:
            kind: Reference kind (unused).
            name: Referenced name (unused).

        Returns:
            Always ``Unknown``.

        Raises:
            None.
        """
        return Unknown()


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Everything ``validate`` needs besides the parsed file.

    Attributes:
        registry: Loaded Definitions.
        version: Active Game Version.
        file: Path of the file being validated; its extension selects the
            root structure and it is stamped on every Diagnostic.
        numeric: Numeric strictness preferences.
        lookup: Reference lookup; the default reports every reference as
            unknown.
    """

    registry: Registry
    version: GameVersion
    file: Path = field(default_factory=Path)
    numeric: NumericPrefs = field(default_factory=NumericPrefs)
    lookup: ReferenceLookup = field(default_factory=NullReferenceLookup)


@dataclass(frozen=True, slots=True)
class _Rule:
    """The value rule of a field, selector or value repeat."""

    type: str | None
    validation: str | None
    values: tuple[str, ...] | None
    constraint: str | None


class StructureCursor:
    """Definition nodes of one block plus the keys seen so far.

    Attributes:
        active: Gate-filtered, branch-expanded Definition nodes.
        plain: Key name mapped to its non-iterative Definition node.
        counts: Count key mapped to its iterative field.
        repeats: Repeat key mapped to the iterative fields using it.
        seen: Keys of Definition nodes that matched a file node.
        position: Key (plain name, or count key of an iterative field) mapped
            to the index of its Definition node in ``active``.
        first: Key mapped to the first file node that used it (for the
            duplicate check).
        placed: ``(file node, declared position)`` of every file node that
            takes a position in the declared order, in file order.
    """

    __slots__ = ("active", "counts", "first", "placed", "plain", "position", "repeats", "seen")

    def __init__(self, active: list[DefNode]) -> None:
        """Index the active Definition nodes.

        Args:
            active: Gate-filtered, branch-expanded nodes in declared order.

        Returns:
            None.

        Raises:
            None.
        """
        self.active = active
        self.plain: dict[str, DefNode] = {}
        self.counts: dict[str, IterativeFieldDef] = {}
        self.repeats: dict[str, list[IterativeFieldDef]] = {}
        self.seen: set[str] = set()
        self.position: dict[str, int] = {}
        self.first: dict[str, Node] = {}
        self.placed: list[tuple[Node, int]] = []
        for index, node in enumerate(active):
            if isinstance(node, IterativeFieldDef):
                self.counts.setdefault(node.count_key, node)
                self.repeats.setdefault(node.name, []).append(node)
                self.position.setdefault(node.count_key, index)
            else:
                self.plain.setdefault(node.name, node)
                self.position.setdefault(node.name, index)

    def place(self, node: Node) -> Node | None:
        """Record a file node that matched a plain field or a count line.

        Args:
            node: The matched file node.

        Returns:
            The first earlier node with the same key when ``node`` is a
            duplicate (it takes no position); None otherwise.

        Raises:
            None.
        """
        earlier = self.first.get(node.key)
        if earlier is not None:
            return earlier
        self.first[node.key] = node
        self.placed.append((node, self.position[node.key]))
        return None

    def out_of_order(self) -> list[tuple[Node, str, str]]:
        """Pick the keys that break the declared order.

        The keys that stay in order are a longest strictly increasing run of
        declared positions (when several runs are equally long, the one
        patience sorting finds), so one misplaced key yields one entry and
        the keys after it are not blamed.

        Returns:
            ``(node, "before" | "after", neighbour key)`` for each misplaced
            key in file order: the key must come before (or after) the
            neighbouring in-order key that is next in declared order.

        Raises:
            None.
        """
        placed = self.placed
        count = len(placed)
        if count < 2:
            return []
        # Patience sorting with back links; tails[k] is the index of the
        # smallest tail of a run of length k + 1.
        tails: list[int] = []
        link: list[int] = [-1] * count
        for i, (_, pos) in enumerate(placed):
            lo, hi = 0, len(tails)
            while lo < hi:
                mid = (lo + hi) // 2
                if placed[tails[mid]][1] < pos:
                    lo = mid + 1
                else:
                    hi = mid
            link[i] = tails[lo - 1] if lo else -1
            if lo == len(tails):
                tails.append(i)
            else:
                tails[lo] = i
        keep: set[int] = set()
        cur = tails[-1]
        while cur != -1:
            keep.add(cur)
            cur = link[cur]
        anchors = sorted((placed[i][1], placed[i][0].key) for i in keep)
        result: list[tuple[Node, str, str]] = []
        for i, (node, pos) in enumerate(placed):
            if i in keep:
                continue
            after = next((key for p, key in anchors if p > pos), None)
            if after is not None:
                result.append((node, "before", after))
            else:
                before = [key for p, key in anchors if p < pos]
                result.append((node, "after", before[-1] if before else ""))
        return result

    def missing_required(self) -> list[str]:
        """List required keys that were not seen, in declared order.

        Returns:
            Key names (the count key for an iterative field).

        Raises:
            None.
        """
        missing: list[str] = []
        for node in self.active:
            key = node.count_key if isinstance(node, IterativeFieldDef) else node.name
            if node.required and key not in self.seen and key not in missing:
                missing.append(key)
        return missing


def definition_warnings(registry: Registry) -> tuple[LoadWarning, ...]:
    """Report malformed ``constraint`` attributes once, at Definition load.

    Uses ``validate_constraint`` for every field and element rule, so the
    value checkers never see a malformed constraint.

    Args:
        registry: Loaded Definitions.

    Returns:
        One ``SOASE-D001`` LoadWarning per offending field or element rule,
        naming the Definition file and the field.

    Raises:
        None.
    """
    warnings: list[LoadWarning] = []
    for name in registry.structure_names:
        struct = registry.structure(name)
        if struct is None:
            continue
        file = registry.structure_file(name) or name
        for node in _walk_defs(struct.children):
            if isinstance(node, FieldDef) and node.constraint is not None:
                problem = validate_constraint(node.validation or node.type or "", node.constraint)
                if problem:
                    warnings.append(LoadWarning(file, f"{name}.{node.name}", problem))
    for name in registry.element_rule_names:
        rule: ElementRuleDef | None = registry.element_rule(name)
        if rule is not None and rule.constraint is not None:
            problem = validate_constraint(rule.validation or rule.type or "", rule.constraint)
            if problem:
                warnings.append(LoadWarning("element_rules", name, problem))
    return tuple(warnings)


def _walk_defs(nodes: Iterable[DefNode]) -> Iterable[DefNode]:
    """Yield every Definition node in a tree, depth first.

    Args:
        nodes: Top-level Definition nodes.

    Returns:
        An iterator over all nodes including nested ones.

    Raises:
        None.
    """
    for node in nodes:
        yield node
        if isinstance(node, IterativeFieldDef):
            yield from _walk_defs(node.children)
        elif isinstance(node, ConditionFieldDef):
            for branch in (node.branches or {}).values():
                yield from _walk_defs(branch)


def _is_ai_use_time_buff_type(node: Node, nodes: Sequence[Node], label: str) -> bool:
    """Tell whether a repeated ``buffType`` is the one the ``aiUseTime`` branch declares.

    Args:
        node: The repeated plain key.
        nodes: The block's child nodes.
        label: Name of the block's structure.

    Returns:
        True for the second ``buffType`` of an Ability block that follows an
        ``aiUseTime`` line with the value ``OnlyWhenManyTargetsInCombatDoNotHaveBuff``.

    Raises:
        None.
    """
    if label != AI_USE_TIME_BUFF_ROOT or node.key != AI_USE_TIME_BUFF_KEY:
        return False
    uses = [n for n in nodes if n.key == AI_USE_TIME_BUFF_KEY]
    if len(uses) < 2 or uses[1] is not node:
        return False
    selector = next((n for n in nodes if n.key == AI_USE_TIME_KEY), None)
    return (
        selector is not None
        and selector.key_span.line < node.key_span.line
        and _text_of(selector.value) == AI_USE_TIME_BUFF_VALUE
    )


def _text_of(value: Value | None) -> str | None:
    """Return the text a scalar value is matched by.

    Args:
        value: Parsed value or None.

    Returns:
        The quoted text, the ``TRUE``/``FALSE`` word or the raw token; None
        for a list or a missing value.

    Raises:
        None.
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


def _member_text(value: Value | None) -> str | None:
    """Return the text an enumeration member is compared with.

    The written form must match the member: ``TRUE`` and ``FALSE`` members
    are unquoted booleans, words are quoted strings, and numeric members are
    either an unquoted number or a quoted string.

    Args:
        value: Parsed value or None.

    Returns:
        The text to compare, or None when the written form is not admitted.

    Raises:
        None.
    """
    match value:
        case StringValue():
            return None if value.text in ("TRUE", "FALSE") else value.text
        case BoolValue():
            return "TRUE" if value.value else "FALSE"
        case NumberValue():
            return value.raw
        case _:
            return None


def _line_span(node: Node) -> Span:
    """Span from the start of a node's key to the end of its value.

    Args:
        node: Parsed node.

    Returns:
        The span of the node's own line.

    Raises:
        None.
    """
    end = node.value_span or node.key_span
    return Span(node.key_span.line, node.key_span.col, end.end_line, end.end_col)


def _value_span(node: Node) -> Span:
    """Span of a node's value, or of its key when it has none.

    Args:
        node: Parsed node.

    Returns:
        The span to report a value problem on.

    Raises:
        None.
    """
    return node.value_span or node.key_span


_PRIMITIVES = {
    "Boolean": check_boolean,
    "Integer": check_integer,
    "Decimal": check_decimal,
    "Color": check_color,
    "Position": check_position,
    "Coordinate": check_coordinate,
    "Any": check_any,
}


class _Walker:
    """Single-use state for one ``validate`` call."""

    def __init__(self, ctx: ValidationContext) -> None:
        """Create a walker.

        Args:
            ctx: Validation context.

        Returns:
            None.

        Raises:
            None.
        """
        self.ctx = ctx
        self.registry = ctx.registry
        self.diags: list[Diagnostic] = []
        # Version whose capability set applies to the file; ``run`` narrows it
        # to the file's SinsArchiveVersion level.
        self.version = ctx.version
        self.archive_version: int | None = None
        self._gates: dict[str | None, bool] = {}
        # State for the V080 pass, by node id: lines matched to a known field,
        # count line or repeat; matched lines whose block has no structure;
        # lines reported as unknown keys; the keys each repeat block defines;
        # and the repeats that follow each count line.
        self._matched: set[int] = set()
        self._flagged: set[int] = set()
        self._unknown_ids: set[int] = set()
        self._block_keys: dict[int, frozenset[str]] = {}
        self._runs: dict[int, list[Node]] = {}
        self._roots: Sequence[Node] = ()
        self._declared: dict[str, tuple[str, ...]] = {}

    def allowed(self, gate: str | None) -> bool:
        """Evaluate a version gate for the active Game Version (memoised).

        Args:
            gate: Gate expression or None.

        Returns:
            True when the element is defined for the active version.

        Raises:
            None.
        """
        cached = self._gates.get(gate)
        if cached is None:
            cached = gate_allows(gate, self.version)
            self._gates[gate] = cached
        return cached

    def emit(self, span: Span, code: str, message: str) -> None:
        """Record a Diagnostic at its catalogue severity.

        Args:
            span: Where the problem is.
            code: Diagnostic code.
            message: Human-readable message.

        Returns:
            None.

        Raises:
            None.
        """
        severity = CODE_CATALOGUE[code].severity if code in CODE_CATALOGUE else Severity.ERROR
        self.diags.append(Diagnostic(self.ctx.file, span.to_range(), severity, code, message))

    def _structure_allowed(self, name: str) -> StructureDef | None:
        """Look up a structure that is defined for the active version.

        Args:
            name: Structure name.

        Returns:
            The structure, or None when absent or gated out.

        Raises:
            None.
        """
        struct = self.registry.structure(name)
        if struct is None or not self.allowed(struct.version):
            return None
        return struct

    def run(self, parsed: ParsedFile) -> list[Diagnostic]:
        """Validate a whole file.

        Args:
            parsed: The parsed file.

        Returns:
            The Diagnostics found.

        Raises:
            None.
        """
        self._set_file_version(parsed)
        self._roots = parsed.nodes
        ext = self.ctx.file.suffix.lower()
        header_end = len(parsed.header) if parsed.header else 0
        anchor = Span(0, 0, 0, header_end)
        nodes = list(parsed.nodes)
        if ext == ENTITY_EXTENSION:
            root = self._entity_root(nodes, anchor)
            if root is None:
                return self.diags
            nodes = [n for n in nodes if n.key != ENTITY_TYPE_KEY or n.parent is not None]
        else:
            root = self.registry.structure_for_extension(ext)
            if root is None or not self.allowed(root.version):
                return self.diags
        if parsed.header == "TXT2" and not self._defines(root, ARCHIVE_VERSION_KEY):
            nodes = [n for n in nodes if n.key != ARCHIVE_VERSION_KEY]
        self._scope(root.children, nodes, None, root.name, anchor)
        self._check_indentation(parsed.nodes)
        return self.diags

    def _set_file_version(self, parsed: ParsedFile) -> None:
        """Choose the version whose rules apply to this file.

        A ``TXT2`` file is validated at its own ``SinsArchiveVersion`` level,
        capped at the project's Game Version; ``TXT`` files, and files whose
        version is missing, malformed, unknown or newer than the project, use
        the project's Game Version.

        Args:
            parsed: The parsed file.

        Returns:
            None.

        Raises:
            None.
        """
        if parsed.header != "TXT2":
            return
        node = next((n for n in parsed.nodes if n.key == ARCHIVE_VERSION_KEY), None)
        if node is None or not isinstance(node.value, NumberValue):
            return
        if not node.value.is_integer:
            return
        self.archive_version = int(node.value.value)
        self.version = effective_version(self.archive_version, self.ctx.version)

    def _introduced_hint(self, defs: Iterable[DefNode], key: str) -> str | None:
        """Explain a key that is defined for the project but newer than the file.

        Args:
            defs: Unexpanded Definition nodes of the block.
            key: The unknown key.

        Returns:
            Text such as ``'x' was introduced in Rebellion 194; this file is
            SinsArchiveVersion 193``, or None when the key is not gated out by
            the file's version alone.

        Raises:
            None.
        """
        if self.version is self.ctx.version:
            return None
        for node in defs:
            names = {node.name}
            if isinstance(node, IterativeFieldDef):
                names.add(node.count_key)
            if key not in names or self.allowed(node.version):
                continue
            if not gate_allows(node.version, self.ctx.version):
                continue
            since = introduced_in(node.version)
            if since is not None:
                return (
                    f"'{key}' was introduced in {display_name(since)}; "
                    f"this file is SinsArchiveVersion {self.archive_version}"
                )
        return None

    def _defines(self, struct: StructureDef, key: str) -> bool:
        """Whether a structure defines a top-level key.

        Args:
            struct: The structure.
            key: Key name.

        Returns:
            True when a child node has that name.

        Raises:
            None.
        """
        return any(node.name == key for node in struct.children)

    def _entity_root(self, nodes: list[Node], anchor: Span) -> StructureDef | None:
        """Pick the root structure of an ``.entity`` file from ``entityType``.

        Args:
            nodes: Top-level nodes.
            anchor: Span for a missing-field Diagnostic.

        Returns:
            The structure, or None when it cannot be chosen (a Diagnostic has
            been recorded).

        Raises:
            None.
        """
        node = next((n for n in nodes if n.key == ENTITY_TYPE_KEY), None)
        if node is None:
            self.emit(anchor, V040, f"Required field '{ENTITY_TYPE_KEY}' is missing in the file")
            return None
        text = node.value.text if isinstance(node.value, StringValue) else None
        enum = self.registry.enum(ENTITY_TYPE_ENUM)
        if text is None:
            self.emit(
                _value_span(node),
                V010,
                f"{ENTITY_TYPE_KEY} must be a quoted entity type name",
            )
            return None
        known = enum is not None and self._enum_allows(enum, text)
        struct = self._structure_allowed(text) if known else None
        if struct is None:
            self.emit(
                _value_span(node),
                V010,
                f"Unknown entityType '{text}' for {self.version.value}",
            )
        return struct

    def _expand(self, defs: Iterable[DefNode], nodes: Sequence[Node], out: list[DefNode]) -> None:
        """Gate-filter Definition nodes and merge the selected branches.

        Args:
            defs: Definition nodes to expand.
            nodes: Sibling file nodes, searched for each selector.
            out: Receives the active nodes in declared order.

        Returns:
            None.

        Raises:
            None.
        """
        for node in defs:
            if not self.allowed(node.version):
                continue
            if isinstance(node, StructureReferenceDef):
                struct = self.registry.structure(node.structure)
                if struct is not None and not self.allowed(struct.version):
                    continue
            out.append(node)
            if isinstance(node, ConditionFieldDef) and node.branches:
                selector = next((n for n in nodes if n.key == node.name), None)
                text = _text_of(selector.value) if selector is not None else None
                if text is not None and text in node.branches:
                    self._expand(node.branches[text], nodes, out)

    def _scope(
        self,
        defs: Iterable[DefNode],
        nodes: Sequence[Node],
        owner: Node | None,
        label: str,
        anchor: Span,
        skip_required: bool = False,
    ) -> StructureCursor:
        """Validate sibling nodes against Definition nodes.

        Args:
            defs: Definition nodes of the block.
            nodes: The block's child nodes.
            owner: The block's node, or None for the file root.
            label: Name used in messages.
            anchor: Span for missing required fields when ``owner`` is None.
            skip_required: Do not report missing required fields.

        Returns:
            The cursor, after the walk.

        Raises:
            None.
        """
        active: list[DefNode] = []
        self._expand(defs, nodes, active)
        cursor = StructureCursor(active)
        self._walk_nodes(cursor, defs, nodes, label)
        if not skip_required:
            where = owner.key_span if owner is not None else anchor
            for key in cursor.missing_required():
                self.emit(where, V040, f"Required field '{key}' is missing in {label}")
        return cursor

    def _walk_nodes(
        self,
        cursor: StructureCursor,
        defs: Iterable[DefNode],
        nodes: Sequence[Node],
        label: str,
    ) -> None:
        """Match each sibling against the cursor's Definition nodes.

        Args:
            cursor: Cursor for the block.
            defs: The unexpanded Definition nodes (for branch hints).
            nodes: The block's child nodes.
            label: Name used in messages.

        Returns:
            None.

        Raises:
            None.
        """
        i = 0
        while i < len(nodes):
            node = nodes[i]
            iterative = cursor.counts.get(node.key)
            if iterative is not None:
                self._place(cursor, node, nodes, label)
                self._matched.add(id(node))
                i = self._iterate(cursor, iterative, nodes, i, label)
                continue
            definition = cursor.plain.get(node.key)
            if definition is None:
                self._unknown(cursor, defs, node, label)
            else:
                self._place(cursor, node, nodes, label)
                self._matched.add(id(node))
                cursor.seen.add(node.key)
                self._check_node(definition, node, nodes, label)
            i += 1
        for node, side, neighbour in cursor.out_of_order():
            self.emit(
                node.key_span,
                V060,
                f"'{node.key}' is out of order in {label}: it must come {side} '{neighbour}'",
            )

    def _place(
        self, cursor: StructureCursor, node: Node, nodes: Sequence[Node], label: str
    ) -> None:
        """Give a matched key its declared position or report a duplicate.

        Args:
            cursor: Cursor for the block.
            node: A plain field or a count line.
            nodes: The block's child nodes.
            label: Name used in messages.

        Returns:
            None.

        Raises:
            None.
        """
        earlier = cursor.place(node)
        if earlier is not None and not _is_ai_use_time_buff_type(node, nodes, label):
            self.emit(
                node.key_span,
                V070,
                f"Duplicate key '{node.key}' in {label}; first used on line "
                f"{earlier.key_span.line + 1}",
            )

    def _unknown(
        self, cursor: StructureCursor, defs: Iterable[DefNode], node: Node, label: str
    ) -> None:
        """Report a key that no active Definition node matches.

        Args:
            cursor: Cursor for the block.
            defs: The unexpanded Definition nodes (for branch hints).
            node: The unmatched node.
            label: Name used in messages.

        Returns:
            None.

        Raises:
            None.
        """
        if not node.key:
            self.emit(node.key_span, V020, f"Unexpected list row in {label}")
            return
        owners = cursor.repeats.get(node.key)
        if owners:
            if node.value is None:
                self._block_keys[id(node)] = frozenset(
                    child.count_key if isinstance(child, IterativeFieldDef) else child.name
                    for it in owners
                    for child in it.children
                    if self.allowed(child.version)
                )
            counts = ", ".join(sorted({it.count_key for it in owners}))
            self.emit(
                node.key_span,
                V030,
                f"'{node.key}' is a repeated entry and must follow its count line ({counts})",
            )
            return
        self._unknown_ids.add(id(node))
        newer = self._introduced_hint(defs, node.key)
        if newer:
            self.emit(node.key_span, V020, newer)
            return
        hint = self._branch_hint(defs, node.key)
        suffix = f" ({hint})" if hint else ""
        self.emit(node.key_span, V020, f"Unknown key '{node.key}' in {label}{suffix}")

    def _branch_hint(self, defs: Iterable[DefNode], key: str) -> str | None:
        """Name the branch that defines a key, if one does.

        Args:
            defs: Unexpanded Definition nodes of the block.
            key: The unknown key.

        Returns:
            Text such as ``only when type is "Foo"``, or None.

        Raises:
            None.
        """
        for node in defs:
            if isinstance(node, ConditionFieldDef) and node.branches:
                for value, branch in node.branches.items():
                    if any(d.name == key and self.allowed(d.version) for d in branch):
                        return f"defined only when {node.name} is {value}"
        return None

    def _check_node(
        self,
        definition: DefNode,
        node: Node,
        siblings: Sequence[Node],
        label: str,
    ) -> None:
        """Validate one node against its non-iterative Definition node.

        Args:
            definition: The matching Definition node.
            node: The file node.
            siblings: The block's nodes (for a condition reference selector).
            label: Name used in messages.

        Returns:
            None.

        Raises:
            None.
        """
        if isinstance(definition, FieldDef):
            self._check_value(node, self._field_rule(definition))
        elif isinstance(definition, ConditionFieldDef):
            self._check_value(node, _Rule(definition.type, definition.validation, None, None))
        elif isinstance(definition, StructureReferenceDef):
            self._check_block(node, definition.structure)
        elif isinstance(definition, ConditionReferenceDef):
            selector = next((n for n in siblings if n.key == definition.selector), None)
            text = _text_of(selector.value) if selector is not None else None
            target = definition.cases.get(text) if text is not None else None
            if target is None:
                self._flagged.add(id(node))
                self.emit(
                    node.key_span,
                    V020,
                    f"No structure is defined for '{node.key}' when {definition.selector} "
                    f"is {text!r}",
                )
            else:
                self._check_block(node, target)

    def _field_rule(self, definition: FieldDef) -> _Rule:
        """Build the value rule of a field.

        A field that names no type, validation or values takes the element
        rule of the same name (15 such fields in the bundled Definitions, all
        ``isDamageShared`` with a ``Boolean`` element rule).

        Args:
            definition: The field.

        Returns:
            The rule to check its value against.

        Raises:
            None.
        """
        if not (definition.type or definition.validation or definition.values):
            shared = self.registry.element_rule(definition.name)
            if shared is not None:
                return _Rule(shared.type, shared.validation, shared.values, shared.constraint)
        values = definition.values
        if definition.values_from is not None:
            values = (*(values or ()), *self._declared_values(definition.values_from))
        return _Rule(definition.type, definition.validation, values, definition.constraint)

    def _declared_values(self, path: str) -> tuple[str, ...]:
        """Collect the string values a key path names anywhere in the file.

        The path is read from the file root, one key per segment, so values
        declared after the field that uses them are found too.

        Args:
            path: Dotted key path such as ``player.designName``.

        Returns:
            The quoted values in file order (empty when the file has none).

        Raises:
            None.
        """
        cached = self._declared.get(path)
        if cached is None:
            level: Sequence[Node] = self._roots
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

    def _check_block(self, node: Node, structure_name: str) -> None:
        """Validate a block node against a named structure.

        Args:
            node: The block node.
            structure_name: Name of the structure describing it.

        Returns:
            None.

        Raises:
            None.
        """
        if node.value is not None:
            self.emit(_value_span(node), V050, f"'{node.key}' must be a block, found a value")
            return
        struct = self.registry.structure(structure_name)
        if struct is None:
            return
        self._scope(struct.children, node.children, node, struct.name, node.key_span)

    def _iterate(
        self,
        cursor: StructureCursor,
        iterative: IterativeFieldDef,
        nodes: Sequence[Node],
        index: int,
        label: str,
    ) -> int:
        """Validate a count line and the repeats that follow it.

        Args:
            cursor: Cursor for the block.
            iterative: The iterative field the count line belongs to.
            nodes: The block's child nodes.
            index: Index of the count line.
            label: Name used in messages.

        Returns:
            Index of the first node after the repeats.

        Raises:
            None.
        """
        count_node = nodes[index]
        cursor.seen.add(count_node.key)
        count = self._count_of(count_node)
        flat = bool(iterative.children) and iterative.children[0].name == iterative.name
        repeats: list[Node] = []
        if flat:
            end, found = self._flat_run(iterative, nodes, index + 1, repeats)
        else:
            end, found = self._repeat_run(cursor, iterative, nodes, index + 1, repeats)
        self._runs[id(count_node)] = repeats
        if count is not None:
            line = _line_span(count_node)
            if iterative.limit is not None and count > iterative.limit:
                self.emit(
                    line,
                    V030,
                    f"{count_node.key} {count} exceeds the limit of {iterative.limit}",
                )
            if count != found:
                self.emit(
                    line,
                    V030,
                    f"{count_node.key} is {count} but {found} '{iterative.name}' "
                    f"{'entries' if found != 1 else 'entry'} follow",
                )
        return end

    def _count_of(self, node: Node) -> int | None:
        """Read a count line's value.

        Args:
            node: The count line.

        Returns:
            The count, or None after recording a Diagnostic for a bad value.

        Raises:
            None.
        """
        value = node.value
        if isinstance(value, NumberValue) and value.is_integer and int(value.value) >= 0:
            return int(value.value)
        self.emit(
            _value_span(node),
            V050,
            f"{node.key} must be a non-negative integer count",
        )
        return None

    def _repeat_run(
        self,
        cursor: StructureCursor,
        iterative: IterativeFieldDef,
        nodes: Sequence[Node],
        start: int,
        repeats: list[Node],
    ) -> tuple[int, int]:
        """Validate the consecutive block or value repeats after a count line.

        A line that follows a block repeat at the repeat's own indentation,
        has a value, is unknown to the enclosing block and is a field of the
        repeat block belongs to that repeat, together with the deeper lines
        after it.

        Args:
            cursor: Cursor for the block that holds the run.
            iterative: The iterative field.
            nodes: The block's child nodes.
            start: Index just after the count line.
            repeats: Receives the repeat nodes of the run.

        Returns:
            The index after the run and the number of repeats in it.

        Raises:
            None.
        """
        end = start
        found = 0
        while end < len(nodes) and nodes[end].key == iterative.name:
            repeat = nodes[end]
            repeats.append(repeat)
            found += 1
            self._matched.add(id(repeat))
            end += 1
            if iterative.children:
                if repeat.value is not None:
                    self.emit(
                        _value_span(repeat),
                        V050,
                        f"'{repeat.key}' must be a block, found a value",
                    )
                    continue
                members = list(repeat.children)
                keys = self._repeat_keys(iterative, repeat)
                while end < len(nodes) and self._is_shallow_member(
                    cursor, iterative, repeat, nodes[end], keys
                ):
                    members.append(nodes[end])
                    end += 1
                    while end < len(nodes) and nodes[end].indent > repeat.indent:
                        members.append(nodes[end])
                        end += 1
                inner = self._scope(
                    iterative.children,
                    members,
                    repeat,
                    repeat.key,
                    repeat.key_span,
                )
                self._block_keys[id(repeat)] = frozenset(inner.plain) | frozenset(inner.counts)
            else:
                self._check_value(repeat, _Rule(iterative.type, iterative.validation, None, None))
        return end, found

    def _repeat_keys(self, iterative: IterativeFieldDef, repeat: Node) -> frozenset[str]:
        """List the keys a repeat block defines.

        Args:
            iterative: The iterative field the repeat belongs to.
            repeat: The repeat block.

        Returns:
            Plain field names and count keys active for the repeat.

        Raises:
            None.
        """
        active: list[DefNode] = []
        self._expand(iterative.children, repeat.children, active)
        inner = StructureCursor(active)
        return frozenset(inner.plain) | frozenset(inner.counts)

    @staticmethod
    def _is_shallow_member(
        cursor: StructureCursor,
        iterative: IterativeFieldDef,
        repeat: Node,
        node: Node,
        keys: frozenset[str],
    ) -> bool:
        """Whether a line after a repeat block is a member written one level too shallow.

        Args:
            cursor: Cursor for the block that holds the run.
            iterative: The iterative field the repeat belongs to.
            repeat: The repeat block.
            node: The line right after the repeat.
            keys: Keys the repeat block defines.

        Returns:
            True for a line with a value whose key the repeat block defines
            and the enclosing block does not.

        Raises:
            None.
        """
        key = node.key
        return (
            node.value is not None
            and node.indent == repeat.indent
            and key != iterative.name
            and key in keys
            and key not in cursor.plain
            and key not in cursor.counts
            and key not in cursor.repeats
        )

    def _flat_run(
        self,
        iterative: IterativeFieldDef,
        nodes: Sequence[Node],
        start: int,
        repeats: list[Node],
    ) -> tuple[int, int]:
        """Validate sequences of sibling lines after a count line.

        Each sequence starts with the selector line (named like the iteration)
        and continues with the sibling lines the selected branch and the other
        children define.

        Args:
            iterative: The iterative field.
            nodes: The block's child nodes.
            start: Index just after the count line.
            repeats: Receives the selector node of each sequence.

        Returns:
            The index after the run and the number of sequences in it.

        Raises:
            None.
        """
        selector_def = iterative.children[0]
        rest = iterative.children[1:]
        rule = _Rule(
            getattr(selector_def, "type", None),
            getattr(selector_def, "validation", None),
            getattr(selector_def, "values", None),
            getattr(selector_def, "constraint", None),
        )
        index = start
        found = 0
        while index < len(nodes) and nodes[index].key == iterative.name:
            selector = nodes[index]
            repeats.append(selector)
            self._matched.add(id(selector))
            found += 1
            self._check_value(selector, rule)
            defs: list[DefNode] = []
            # Declared order: the selected branch sits right after the selector.
            if isinstance(selector_def, ConditionFieldDef) and selector_def.branches:
                text = _text_of(selector.value)
                if text is not None and text in selector_def.branches:
                    self._expand(selector_def.branches[text], nodes[index + 1 :], defs)
            self._expand(rest, nodes[index + 1 :], defs)
            names = {d.name for d in defs}
            end = index + 1
            taken: set[str] = set()
            while (
                end < len(nodes)
                and nodes[end].key in names
                and nodes[end].key != iterative.name
                and nodes[end].key not in taken
            ):
                taken.add(nodes[end].key)
                end += 1
            self._scope(defs, nodes[index + 1 : end], selector, selector.key, selector.key_span)
            index = end
        return index, found

    def _check_indentation(self, roots: Sequence[Node]) -> None:
        """Report lines indented deeper than a value line (``SOASE-V080``).

        Walks every node in source order. A line deeper than the line right
        before it is expected only when that line is a block header (no
        value), or the count line of an iterative field and the deeper line
        is the first repeat of its run, exactly one level deeper. Otherwise
        the deeper line is reported when the previous line is a known line:

        * a plain field, count line or repeat matched in its block (a count
          mismatch on the count line does not change that), or
        * an unknown key (``SOASE-V020``) that is a field of the repeat block
          (an entry of an iterative field) ending right before it at the same
          indentation: the line was meant to sit one level deeper, inside
          that repeat. This applies to a repeat that is unplaced
          (``SOASE-V030``), because a placed repeat takes such a line as
          one of its own members.

        Every other previous line is skipped: other unknown keys (including
        keys that a preceding non-repeat block defines, which is a
        Definition placement question), repeats without a count line, list
        rows, and everything inside blocks that no Definition matched.

        Repeats of one run sit at the count line's level or exactly one
        level deeper, one style per run; the first repeat that breaks the
        style of the first repeat is reported once.

        Args:
            roots: Top-level nodes of the file.

        Returns:
            None.

        Raises:
            None.
        """
        order: list[Node] = []
        stack = list(reversed(roots))
        while stack:
            node = stack.pop()
            order.append(node)
            stack.extend(reversed(node.children))
        by_id = {id(n): n for n in order}
        later_repeats = {id(r) for run in self._runs.values() for r in run[1:]}
        for index in range(1, len(order)):
            prev, node = order[index - 1], order[index]
            if node.indent <= prev.indent or prev.value is None:
                continue
            if id(node) in later_repeats:
                continue  # judged by the run-style check below
            if not self._known_line(prev, order[index - 2] if index > 1 else None):
                continue
            run = self._runs.get(id(prev))
            if run and run[0] is node and node.indent - prev.indent == 1:
                continue
            line = prev.key_span.line + 1
            if run and run[0] is node:
                message = (
                    f"'{node.key}' is indented {node.indent - prev.indent} levels under count "
                    f"line '{prev.key}' (line {line}); repeats sit at the count line's level "
                    "or one level deeper"
                )
            else:
                message = (
                    f"'{node.key}' is indented under '{prev.key}' on line {line}, which has a "
                    f"value; line {line} is probably under-indented"
                )
            self.emit(node.key_span, V080, message)
        for count_id, run in self._runs.items():
            count_line = by_id.get(count_id)
            if not run or count_line is None or run[0].indent - count_line.indent not in (0, 1):
                continue  # a first repeat at another depth was reported above
            first = run[0]
            odd = next((r for r in run[1:] if r.indent != first.indent), None)
            if odd is not None:
                self.emit(
                    odd.key_span,
                    V080,
                    f"'{odd.key}' is indented differently from the first '{first.key}' of its "
                    f"run (line {first.key_span.line + 1}); a run uses one indentation",
                )

    def _known_line(self, line: Node, before: Node | None) -> bool:
        """Whether a value line counts as known for the V080 check.

        Args:
            line: The value line before a deeper line.
            before: The line before ``line`` in source order, or None.

        Returns:
            True for a matched field, count line or repeat, and for an
            unknown key that is a field of the repeat block ending right
            before it at the same indentation.

        Raises:
            None.
        """
        if id(line) in self._matched:
            return id(line) not in self._flagged
        if id(line) not in self._unknown_ids:
            return False
        block = before
        while block is not None and block.indent > line.indent:
            block = block.parent
        if block is None or block.indent != line.indent:
            return False
        keys = self._block_keys.get(id(block))
        return keys is not None and line.key in keys

    def _enum_allows(self, enum: EnumDef, text: str) -> bool:
        """Whether a text is a member of an enumeration for the version.

        Args:
            enum: The enumeration.
            text: Candidate member.

        Returns:
            True when the enumeration and the member are defined for the
            active Game Version.

        Raises:
            None.
        """
        if not self.allowed(enum.version):
            return False
        return any(m.name == text and self.allowed(m.version) for m in enum.values)

    def _check_value(self, node: Node, rule: _Rule) -> None:
        """Validate a node's value against a field rule.

        Args:
            node: The file node.
            rule: The value rule.

        Returns:
            None.

        Raises:
            None.
        """
        enum = self.registry.enum(rule.type) if rule.type else None
        validation = rule.validation or rule.type
        if rule.values is not None or enum is not None:
            self._check_enum(node, rule, enum)
            return
        if validation == "Orientation":
            self._report(node, check_orientation(node, self.ctx.numeric))
            return
        if node.children:
            self.emit(_value_span(node), V050, f"'{node.key}' must be a value, found a block")
            return
        if node.value is None:
            if validation == "Any":
                return
            self.emit(node.key_span, V050, f"'{node.key}' needs a value")
            return
        if validation in _PRIMITIVES:
            constraint = rule.constraint
            if constraint is not None and validate_constraint(validation or "", constraint):
                constraint = None
            try:
                result = _PRIMITIVES[validation](node.value, self.ctx.numeric, constraint)
            except ValueError as exc:  # defensive: constraint already screened
                _LOG.debug("constraint rejected by checker: %s", exc)
                result = PrimitiveResult(True)
            self._report(node, result)
        elif validation in REFERENCE_KINDS or validation in UNRESOLVED_NAME_TYPES:
            self._check_name(node, validation or "")

    def _report(self, node: Node, result: PrimitiveResult) -> None:
        """Record a failed primitive result as ``SOASE-V050``.

        Args:
            node: The checked node.
            result: Checker outcome.

        Returns:
            None.

        Raises:
            None.
        """
        if not result.ok:
            self.emit(_value_span(node), V050, f"{node.key}: {result.message}")

    def _check_enum(self, node: Node, rule: _Rule, enum: EnumDef | None) -> None:
        """Validate an enumeration value.

        Args:
            node: The file node.
            rule: The value rule.
            enum: The named enumeration, or None for inline ``values``.

        Returns:
            None.

        Raises:
            None.
        """
        if node.children:
            self.emit(_value_span(node), V050, f"'{node.key}' must be a value, found a block")
            return
        if not isinstance(node.value, StringValue | BoolValue | NumberValue | HexValue):
            self.emit(node.key_span, V050, f"'{node.key}' needs a value")
            return
        text = _member_text(node.value)
        if rule.values is not None:
            ok = text is not None and text in rule.values
        else:
            ok = enum is not None and text is not None and self._enum_allows(enum, text)
        if not ok:
            shown = _text_of(node.value)
            self.emit(
                _value_span(node),
                V050,
                f"{node.key}: {shown!r} is not a valid value for {self.version.value}",
            )

    def _check_name(self, node: Node, kind: str) -> None:
        """Validate a quoted reference name and resolve it.

        Args:
            node: The file node.
            kind: The validation type.

        Returns:
            None.

        Raises:
            None.
        """
        if not isinstance(node.value, StringValue):
            self.emit(_value_span(node), V050, f"{node.key}: expected a quoted {kind} name")
            return
        if kind not in REFERENCE_KINDS or not node.value.text:
            # An empty name means "none" and is never resolved.
            return
        result = self.ctx.lookup.resolve(kind, node.value.text)
        if isinstance(result, NotFound):
            self.emit(
                _value_span(node),
                R010,
                f"Unresolved {kind} reference '{node.value.text}'",
            )


def validate(parsed: ParsedFile, ctx: ValidationContext) -> list[Diagnostic]:
    """Validate a parsed file against the Definitions.

    Args:
        parsed: The parsed file.
        ctx: Registry, Game Version, file path, numeric preferences and the
            reference lookup.

    Returns:
        Validator Diagnostics (``V`` and ``R`` families), in walk order.
        Parser Diagnostics stay in ``parsed.diagnostics``. A file with an
        extension that has no Definition yields an empty list.

    Raises:
        None. Malformed input becomes Diagnostics; a malformed Definition
        ``constraint`` is reported by :func:`definition_warnings`.
    """
    return _Walker(ctx).run(parsed)


__all__ = [
    "REFERENCE_KINDS",
    "UNRESOLVED_NAME_TYPES",
    "Found",
    "NotFound",
    "NullReferenceLookup",
    "ReferenceLookup",
    "ResolveResult",
    "StructureCursor",
    "Unknown",
    "ValidationContext",
    "definition_warnings",
    "validate",
]
