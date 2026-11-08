"""Definition-guided structure of a parsed mod file.

``place`` re-derives block membership from the Definitions. The parser's tree
is the indentation reading of the file; the placed tree this module returns
gives every line the parent its Definition names, whatever its indentation,
and the validator walks that tree. ``place`` is pure: it reads the parsed
nodes, copies them and does no I/O.

Placement
---------
Lines are read in file order with a stack of open blocks. Each block holds
the gate-filtered, branch-expanded Definition nodes of its structure (the
same expansion the validator uses, built by :class:`Expander`). A line goes
to the innermost open block that defines its key and closes the blocks
inside it. When several open blocks define the key, the innermost one with
a member at the line's indentation wins, otherwise the innermost. A line
without a value opens a block when its key is a structure reference, a
condition reference or a repeat with children; a line with a value never
opens one, so the lines under it are placed by Definition as well.

A condition selector placed in a block rebuilds the block's Definition view.
After a count line, the repeats that follow it directly form a run; for a
run of sibling sequences (a selector line followed by the lines its branch
defines) the continuation keys belong to the block that holds the run.

A key no open block defines is unknown: it joins the innermost open block
whose own line is less indented. The lines under it, the lines under a
value-less line that is not a block (``Orientation``) and the lines under a
block whose structure cannot be chosen stay under it by indentation and are
not placed or checked.

Indentation
-----------
Indentation is compared by order and equality only, so tab, space and mixed
indentation behave alike. The members of a block are expected at the
indentation most of its placed members use (ties: the first such indentation
in the file), restricted to indentations deeper than the one the block's own
line is expected at. A block with no such member is expected one unit
deeper. The members of the root are expected at the indentation most of them
use. A counted run sits at the count line's expected indentation, or at one
deeper indentation shared by the whole run, set by its first line. The
expected indentation of a block line, not its actual one, is the base of its
members, so a block written at another depth as a whole gives one finding.
Consecutive members of one block at the same wrong indentation give one
finding, on the first. Unknown keys, their subtrees and lines that no run
owns are not checked.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from soase_validator.engine.parser import (
    BoolValue,
    HexValue,
    Node,
    NumberValue,
    StringValue,
    Value,
)
from soase_validator.engine.registry import (
    ConditionFieldDef,
    ConditionReferenceDef,
    IterativeFieldDef,
    Registry,
    StructureDef,
    StructureReferenceDef,
)
from soase_validator.engine.registry import Node as DefNode

_PLAIN = "plain"
_RUN = "run"
_UNCHECKED = "unchecked"


def text_of(value: Value | None) -> str | None:
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


class Expander:
    """Expands Definition nodes for the active Game Version.

    One instance serves the validator and the placement, so "which keys does
    this block define" has a single answer.
    """

    def __init__(self, registry: Registry, allowed: Callable[[str | None], bool]) -> None:
        """Create an expander.

        Args:
            registry: Loaded Definitions.
            allowed: Evaluates a version gate for the active Game Version.

        Returns:
            None.

        Raises:
            None.
        """
        self.registry = registry
        self.allowed = allowed

    def structure(self, name: str) -> StructureDef | None:
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

    def expand(self, defs: Iterable[DefNode], nodes: Sequence[Node], out: list[DefNode]) -> None:
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
                text = text_of(selector.value) if selector is not None else None
                if text is not None and text in node.branches:
                    self.expand(node.branches[text], nodes, out)


@dataclass(frozen=True, slots=True)
class IndentFinding:
    """A line whose indentation differs from the expected one.

    Attributes:
        node: The placed node the finding is reported on.
        message: Human-readable message naming the line or block to match.
    """

    node: Node
    message: str


@dataclass(frozen=True, slots=True)
class Placement:
    """Result of :func:`place`.

    Attributes:
        nodes: Top-level nodes of the placed tree.
        findings: Indentation findings in source order of the checked block.
    """

    nodes: tuple[Node, ...]
    findings: tuple[IndentFinding, ...] = ()


@dataclass(slots=True)
class _Run:
    """The repeats that follow one count line."""

    iterative: IterativeFieldDef
    flat: bool
    members: list[_Member] = field(default_factory=list)
    extra: dict[str, DefNode] = field(default_factory=dict)
    taken: set[str] = field(default_factory=set)
    start: int = 0


@dataclass(slots=True)
class _Member:
    """A placed line with the way its indentation is judged."""

    node: Node
    kind: str
    run: _Run | None = None
    opens: _Block | None = None


class _Block:
    """An open block: its Definition view and the lines placed into it."""

    def __init__(
        self,
        node: Node | None,
        defs: Sequence[DefNode],
        expander: Expander,
        header_keys: frozenset[str] = frozenset(),
    ) -> None:
        """Create a block and build its Definition view.

        Args:
            node: The placed node of the block line; None for the root.
            defs: The block's unexpanded Definition nodes.
            expander: Shared Definition expansion.
            header_keys: Keys the root accepts without a Definition.

        Returns:
            None.

        Raises:
            None.
        """
        self.node = node
        self.defs = defs
        self.expander = expander
        self.header_keys = header_keys
        self.placed: list[Node] = []
        self.members: list[_Member] = []
        self.indents: set[int] = set()
        self.run: _Run | None = None
        self.last_count: dict[str, IterativeFieldDef] = {}
        self.line_expected: int | None = None
        self.cursor = StructureCursor([])
        self.rebuild()

    def rebuild(self) -> None:
        """Rebuild the Definition view from the lines placed so far.

        Returns:
            None.

        Raises:
            None.
        """
        active: list[DefNode] = []
        self.expander.expand(self.defs, self.placed, active)
        self.cursor = StructureCursor(active)

    def defines(self, key: str) -> bool:
        """Whether the block can take a line with this key.

        Args:
            key: The line's key.

        Returns:
            True for a field, count key, repeat key, header key or an open
            sequence's continuation key.

        Raises:
            None.
        """
        cursor = self.cursor
        run = self.run
        return (
            key in cursor.plain
            or key in cursor.counts
            or key in cursor.repeats
            or key in self.header_keys
            or (run is not None and key in run.extra and key not in run.taken)
        )


def _clone(src: Node, parent: Node | None) -> Node:
    """Copy a node and its subtree, keeping the indentation reading.

    Args:
        src: Node to copy.
        parent: Parent of the copy.

    Returns:
        The copy.

    Raises:
        None.
    """
    copy = Node(
        key=src.key,
        key_span=src.key_span,
        value=src.value,
        value_span=src.value_span,
        extent=src.extent,
        parent=parent,
        indent=src.indent,
    )
    copy.children = [_clone(child, copy) for child in src.children]
    return copy


def _modal(values: Sequence[int]) -> int:
    """Pick the most common value, the first one in the sequence on ties.

    Args:
        values: A non-empty sequence.

    Returns:
        The most common value.

    Raises:
        None.
    """
    counts = Counter(values)
    best = max(counts.values())
    return next(value for value in values if counts[value] == best)


class _Placer:
    """Single-use state for one ``place`` call."""

    def __init__(self, expander: Expander, header_keys: frozenset[str]) -> None:
        """Create a placer.

        Args:
            expander: Shared Definition expansion.
            header_keys: Root keys accepted without a Definition.

        Returns:
            None.

        Raises:
            None.
        """
        self.expander = expander
        self.header_keys = header_keys
        self.top: list[Node] = []
        self.blocks: list[_Block] = []

    def run(self, roots: Sequence[Node], defs: Sequence[DefNode]) -> Placement:
        """Place every line of a file.

        Args:
            roots: Top-level nodes of the parsed file.
            defs: Definition nodes of the root structure.

        Returns:
            The placed tree and the indentation findings.

        Raises:
            None.
        """
        root = _Block(None, defs, self.expander, self.header_keys)
        self.blocks.append(root)
        stack = [root]
        todo = list(reversed(roots))
        while todo:
            src = todo.pop()
            if self._place_line(src, stack):
                todo.extend(reversed(src.children))
        return Placement(tuple(self.top), tuple(self._check()))

    def _target(self, src: Node, stack: list[_Block]) -> _Block | None:
        """Pick the open block that takes a line, closing the blocks inside it.

        Args:
            src: The parsed line.
            stack: Open blocks, outermost first; trimmed to the target.

        Returns:
            The block that defines the key, or None for an unknown key (the
            stack is then trimmed to the block the line joins by indentation).

        Raises:
            None.
        """
        candidates = [i for i, block in enumerate(stack) if block.defines(src.key)]
        if not candidates:
            while (
                len(stack) > 1
                and stack[-1].node is not None
                and (stack[-1].node.indent >= src.indent)
            ):
                stack.pop()
            return None
        pick = candidates[-1]
        if len(candidates) > 1:
            pick = next((i for i in reversed(candidates) if src.indent in stack[i].indents), pick)
        del stack[pick + 1 :]
        return stack[pick]

    def _attach(self, block: _Block, src: Node) -> Node:
        """Add a copy of a line to a block.

        Args:
            block: Receiving block.
            src: The parsed line.

        Returns:
            The placed copy, without children.

        Raises:
            None.
        """
        copy = Node(
            key=src.key,
            key_span=src.key_span,
            value=src.value,
            value_span=src.value_span,
            extent=src.extent,
            parent=block.node,
            indent=src.indent,
        )
        (block.node.children if block.node is not None else self.top).append(copy)
        block.placed.append(copy)
        return copy

    def _place_line(self, src: Node, stack: list[_Block]) -> bool:
        """Place one line.

        Args:
            src: The parsed line.
            stack: Open blocks, outermost first.

        Returns:
            True when the lines under ``src`` are placed on their own; False
            when they stay under it by indentation.

        Raises:
            None.
        """
        target = self._target(src, stack)
        if target is None:
            host = stack[-1]
            copy = self._attach(host, src)
            copy.children = [_clone(child, copy) for child in src.children]
            host.members.append(_Member(copy, _UNCHECKED))
            return False
        copy = self._attach(target, src)
        member, definition, repeat = self._classify(target, copy)
        target.members.append(member)
        if member.kind != _UNCHECKED:
            target.indents.add(src.indent)
        if member.run is not None and member.kind == _RUN and member.run.flat:
            self._refresh_extra(target, member.run)
        if src.value is not None:
            return True
        defs = self._block_defs(target, copy, definition, repeat)
        if defs is None:
            copy.children = [_clone(child, copy) for child in src.children]
            return False
        block = _Block(copy, defs, self.expander)
        self.blocks.append(block)
        member.opens = block
        stack.append(block)
        return True

    def _classify(
        self, target: _Block, copy: Node
    ) -> tuple[_Member, DefNode | None, IterativeFieldDef | None]:
        """Decide how a placed line is judged and which Definition describes it.

        Args:
            target: The receiving block.
            copy: The placed line.

        Returns:
            The member record, the Definition node of the line (None for a
            header key), and the iterative field when the line is a repeat.

        Raises:
            None.
        """
        key = copy.key
        cursor = target.cursor
        run = target.run
        if run is not None and key in run.extra and key not in run.taken:
            run.taken.add(key)
            member = _Member(copy, _RUN, run)
            run.members.append(member)
            return member, run.extra[key], None
        if run is not None and key == run.iterative.name:
            member = _Member(copy, _RUN, run)
            run.members.append(member)
            if run.flat:
                run.taken = set()
                run.start = len(target.placed)
            return member, None, run.iterative
        target.run = None
        iterative = cursor.counts.get(key)
        if iterative is not None:
            flat = bool(iterative.children) and iterative.children[0].name == iterative.name
            target.run = _Run(iterative, flat, start=len(target.placed))
            target.last_count[iterative.name] = iterative
            member = _Member(copy, _PLAIN, target.run)
            return member, None, None
        definition = cursor.plain.get(key)
        if definition is not None:
            if isinstance(definition, ConditionFieldDef):
                target.rebuild()
            return _Member(copy, _PLAIN), definition, None
        if key in cursor.repeats:
            owners = cursor.repeats[key]
            repeat = target.last_count.get(key) or owners[0]
            return _Member(copy, _UNCHECKED), None, repeat
        return _Member(copy, _PLAIN), None, None

    def _refresh_extra(self, target: _Block, run: _Run) -> None:
        """Recompute the keys the open sequence of a flat run can continue with.

        Args:
            target: The block that holds the run.
            run: The run, whose latest sequence starts with a selector line.

        Returns:
            None.

        Raises:
            None.
        """
        iterative = run.iterative
        selector_def = iterative.children[0]
        selector = target.placed[run.start - 1]
        following = target.placed[run.start :]
        defs: list[DefNode] = []
        if isinstance(selector_def, ConditionFieldDef) and selector_def.branches:
            text = text_of(selector.value)
            if text is not None and text in selector_def.branches:
                self.expander.expand(selector_def.branches[text], following, defs)
        self.expander.expand(iterative.children[1:], following, defs)
        run.extra = {d.name: d for d in defs if d.name != iterative.name}

    def _block_defs(
        self,
        target: _Block,
        copy: Node,
        definition: DefNode | None,
        repeat: IterativeFieldDef | None,
    ) -> Sequence[DefNode] | None:
        """Choose the Definition nodes of the block a value-less line opens.

        Args:
            target: The receiving block.
            copy: The placed line.
            definition: Definition node of the line, if any.
            repeat: The iterative field when the line is a repeat.

        Returns:
            The block's Definition nodes, or None when the line opens no block
            or its structure cannot be chosen.

        Raises:
            None.
        """
        if repeat is not None:
            flat = bool(repeat.children) and repeat.children[0].name == repeat.name
            return repeat.children if repeat.children and not flat else None
        if isinstance(definition, StructureReferenceDef):
            struct = self.expander.structure(definition.structure)
            return struct.children if struct is not None else None
        if isinstance(definition, ConditionReferenceDef):
            selector = next((n for n in target.placed if n.key == definition.selector), None)
            text = text_of(selector.value) if selector is not None else None
            name = definition.cases.get(text) if text is not None else None
            struct = self.expander.structure(name) if name is not None else None
            return struct.children if struct is not None else None
        return None

    def _check(self) -> list[IndentFinding]:
        """Compare every checked line with its expected indentation.

        Returns:
            The findings, block by block in the order the blocks opened.

        Raises:
            None.
        """
        out: list[IndentFinding] = []
        for block in self.blocks:
            plain = [m for m in block.members if m.kind == _PLAIN]
            indents = [m.node.indent for m in plain]
            if block.node is None:
                expected = _modal(indents) if indents else 0
            else:
                base = block.line_expected if block.line_expected is not None else block.node.indent
                deeper = [i for i in indents if i > base]
                expected = _modal(deeper) if deeper else base + 1
            reference = next((m for m in plain if m.node.indent == expected), None)
            wrong: int | None = None
            for member in block.members:
                node = member.node
                if member.kind == _UNCHECKED:
                    wrong = None
                    if member.opens is not None:
                        member.opens.line_expected = node.indent
                    continue
                if member.kind == _RUN:
                    continue
                if node.indent == expected:
                    wrong = None
                elif node.indent != wrong:
                    wrong = node.indent
                    out.append(IndentFinding(node, _member_message(block, node, reference)))
                if member.opens is not None:
                    member.opens.line_expected = expected
                if member.run is not None:
                    self._check_run(member, expected, out)
        return out

    @staticmethod
    def _check_run(count: _Member, expected: int, out: list[IndentFinding]) -> None:
        """Compare the repeats of a run with the run's indentation.

        Args:
            count: The count line's member record.
            expected: The count line's expected indentation.
            out: Receives the findings.

        Returns:
            None.

        Raises:
            None.
        """
        run = count.run
        if run is None or not run.members:
            return
        first = run.members[0]
        style = first.node.indent if first.node.indent >= expected else expected
        wrong: int | None = None
        for member in run.members:
            node = member.node
            if node.indent == style:
                wrong = None
            elif node.indent != wrong:
                wrong = node.indent
                if member is first:
                    message = (
                        f"'{node.key}' is less indented than its count line "
                        f"'{count.node.key}' on line {count.node.key_span.line + 1}; "
                        "repeats sit at the count line's indentation or deeper"
                    )
                else:
                    message = (
                        f"'{node.key}' is indented differently from the first "
                        f"'{first.node.key}' of its run on line {first.node.key_span.line + 1}; "
                        "a run uses one indentation"
                    )
                out.append(IndentFinding(node, message))
            if member.opens is not None:
                member.opens.line_expected = style


def _member_message(block: _Block, node: Node, reference: _Member | None) -> str:
    """Build the message for a member at an unexpected indentation.

    Args:
        block: The block that holds the member.
        node: The member line.
        reference: A member of the block at the expected indentation, if any.

    Returns:
        The message naming the line or block the member should match.

    Raises:
        None.
    """
    header = block.node
    where = f"block '{header.key}'" if header is not None else "the file's top level"
    if reference is not None or header is None:
        name = reference.node.key if reference is not None else ""
        line = reference.node.key_span.line + 1 if reference is not None else 1
        return (
            f"'{node.key}' is indented differently from '{name}' on line {line}, "
            f"which is in the same {where}; members of a block share one indentation"
        )
    return (
        f"'{node.key}' is not indented under its block line '{header.key}' on line "
        f"{header.key_span.line + 1}"
    )


def place(
    roots: Sequence[Node],
    defs: Sequence[DefNode],
    expander: Expander,
    header_keys: frozenset[str] = frozenset(),
) -> Placement:
    """Place the lines of a parsed file by Definition.

    Args:
        roots: Top-level nodes of the parsed file.
        defs: Definition nodes of the file's root structure.
        expander: Shared Definition expansion for the active Game Version.
        header_keys: Top-level keys accepted without a Definition.

    Returns:
        The placed tree and the indentation findings. The parsed nodes are
        not changed.

    Raises:
        None.
    """
    return _Placer(expander, header_keys).run(roots, defs)


__all__ = [
    "Expander",
    "IndentFinding",
    "Placement",
    "StructureCursor",
    "place",
    "text_of",
]
