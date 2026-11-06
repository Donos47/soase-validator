"""Tolerant, line-oriented parser for Sins mod text files.

The parser reads ``TXT`` and ``TXT2`` files into a tree of ``Node`` objects
with exact zero-based source positions. It never raises on malformed input:
unparseable lines are skipped with a Diagnostic and parsing continues, so the
parsed portion of a broken file is always returned.

Values are quoted strings, ``TRUE``/``FALSE``, numbers, bare hexadecimal
tokens (colors such as ``ffffffff``) and bracket lists separated by commas or
whitespace. A line that starts with ``[`` is a keyless row. The form
``key = "value"`` (``.constants``) is read as ``key "value"``; any other use of
``=`` (for example ``key= "v"``) is reported as ``SOASE-P002``. Any text
after a complete quoted value on the same line is also ``SOASE-P002``.

Block extents are decided purely by relative indentation using an indent
stack. Tabs and spaces each count as one unit of indentation width.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from soase_validator.engine.diagnostics import P001, P002, P003, P004
from soase_validator.engine.model import Diagnostic, Severity, Span
from soase_validator.engine.versions import GameVersion, archive_level, is_newer_than

HEADERS = ("TXT", "TXT2")
VERSION_KEY = "SinsArchiveVersion"

_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_WS = " \t"
_HEX_RE = re.compile(r"[0-9a-fA-F]+")


@dataclass(frozen=True, slots=True)
class StringValue:
    """A quoted string value.

    Attributes:
        text: Text between the quotes (may be empty).
        terminated: False when the closing quote was missing.
    """

    text: str
    terminated: bool = True


@dataclass(frozen=True, slots=True)
class NumberValue:
    """An unquoted numeric value.

    Attributes:
        raw: The text exactly as written.
        value: Parsed ``int`` (no decimal point or exponent) or ``float``.
    """

    raw: str
    value: int | float

    @property
    def is_integer(self) -> bool:
        """Whether the raw text is written in integer form.

        Returns:
            True when the value has no decimal point or exponent.

        Raises:
            None.
        """
        return isinstance(self.value, int)


@dataclass(frozen=True, slots=True)
class BoolValue:
    """An unquoted ``TRUE`` or ``FALSE`` value.

    Attributes:
        value: The boolean value.
    """

    value: bool


@dataclass(frozen=True, slots=True)
class ListValue:
    """A bracket list of numbers.

    Both real forms are represented: comma separated (``[ 234 , 219 ]``) and
    whitespace separated (``[ 0.000000 0.100000 0.000000 ]``).

    Attributes:
        items: The numbers in order.
        separator: ``","`` for comma separated lists, ``" "`` for whitespace
            separated lists. Lists with fewer than two items use ``","``.
    """

    items: tuple[NumberValue, ...]
    separator: str = ","


@dataclass(frozen=True, slots=True)
class HexValue:
    """An unquoted run of hexadecimal digits that is not a number.

    Colors are written this way, for example ``ffffffff``.

    Attributes:
        raw: The token exactly as written (letters in either case).
    """

    raw: str


Value = StringValue | NumberValue | BoolValue | ListValue | HexValue


@dataclass(slots=True)
class Node:
    """A key with an optional value and optional child nodes.

    Attributes:
        key: Key text (everything before the first run of tabs or spaces).
            Empty for a keyless row, a line that starts with ``[`` and holds
            only a list (the rows under an ``Orientation`` header).
        key_span: Span of the key.
        value: Parsed value, or None for block keys.
        value_span: Span of the value, or None.
        children: Nodes nested under this key.
        parent: Enclosing node, or None at top level.
        extent: Span from the key start to the end of the last descendant.
        indent: Indentation width of the key's line.
    """

    key: str
    key_span: Span
    value: Value | None = None
    value_span: Span | None = None
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False, compare=False)
    extent: Span = field(default_factory=lambda: Span(0, 0, 0, 0))
    indent: int = 0


@dataclass(slots=True)
class ParsedFile:
    """Result of parsing a file.

    Attributes:
        header: ``"TXT"``, ``"TXT2"`` or None when missing.
        nodes: Top-level nodes.
        diagnostics: Parser Diagnostics (P-family).
        complete: False when recovery was needed.
    """

    header: str | None
    nodes: list[Node]
    diagnostics: list[Diagnostic]
    complete: bool = True


def read_text_file(path: Path) -> str:
    """Read a mod file as text.

    Decodes as UTF-8 (dropping a BOM) and falls back to Latin-1.

    Args:
        path: File to read.

    Returns:
        The decoded text.

    Raises:
        OSError: If the file cannot be read.
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _diag(file: Path, span: Span, severity: Severity, code: str, message: str) -> Diagnostic:
    """Build a Diagnostic from a span.

    Args:
        file: File path.
        span: Offending span.
        severity: Severity.
        code: Diagnostic code.
        message: Message text.

    Returns:
        The Diagnostic.

    Raises:
        None.
    """
    return Diagnostic(file, span.to_range(), severity, code, message)


def _number(raw: str) -> NumberValue | None:
    """Parse a numeric token.

    Args:
        raw: Token text.

    Returns:
        A ``NumberValue`` or None when the token is not a number.

    Raises:
        None.
    """
    if not _NUMBER_RE.fullmatch(raw):
        return None
    if re.fullmatch(r"[+-]?\d+", raw):
        return NumberValue(raw, int(raw))
    return NumberValue(raw, float(raw))


def _parse_list(text: str) -> ListValue | None:
    """Parse a bracket list such as ``[ 1 , 2 ]`` or ``[ 1.0 2.0 3.0 ]``.

    A list containing a comma is comma separated (each part is one number);
    otherwise items are separated by whitespace.

    Args:
        text: Text starting with ``[``.

    Returns:
        The list, or None when it is malformed.

    Raises:
        None.
    """
    close = text.find("]")
    if close == -1 or text[close + 1 :].strip():
        return None
    inner = text[1:close].strip()
    if not inner:
        return ListValue(())
    comma = "," in inner
    parts = inner.split(",") if comma else inner.split()
    items: list[NumberValue] = []
    for part in parts:
        num = _number(part.strip())
        if num is None:
            return None
        items.append(num)
    separator = " " if not comma and len(items) > 1 else ","
    return ListValue(tuple(items), separator)


def _skip_equals(line: str, offset: int) -> int:
    """Skip the ``=`` of the ``key = "value"`` form.

    The form is ``key = "value"`` with whitespace on both sides of the ``=``
    and a quoted value. Only that shape is accepted; any other use of ``=``
    is left for the caller to report.

    Args:
        line: The full source line.
        offset: Offset of the first character after the key and its
            whitespace.

    Returns:
        The offset of the opening quote when ``= "`` starts at ``offset``,
        otherwise ``offset`` unchanged.

    Raises:
        None.
    """
    if line[offset : offset + 1] != "=":
        return offset
    after = offset + 1
    pos = after
    while pos < len(line) and line[pos] in _WS:
        pos += 1
    if pos > after and line[pos : pos + 1] == '"':
        return pos
    return offset


def parse(
    text: str,
    file: Path | None = None,
    game_version: GameVersion | None = None,
) -> ParsedFile:
    """Parse mod file text into a tree.

    Args:
        text: Full file text.
        file: Path used in Diagnostics (defaults to an empty path).
        game_version: The project's Game Version. A ``SinsArchiveVersion``
            that is known and not newer than it gives no Diagnostic; an
            unknown or newer one gives an informational ``SOASE-P004``. When
            None, the check is skipped.

    Returns:
        The ``ParsedFile``. Never raises for malformed input.

    Raises:
        None.
    """
    path = file if file is not None else Path()
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    diags: list[Diagnostic] = []
    complete = True
    header: str | None = None
    roots: list[Node] = []
    stack: list[Node] = []

    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    start = 0
    if first is not None and lines[first].strip() in HEADERS:
        header = lines[first].strip()
        start = first + 1
    else:
        complete = False
        diags.append(
            _diag(
                path,
                Span(0, 0, 0, len(lines[0]) if lines else 0),
                Severity.ERROR,
                P001,
                "Missing file header: the first line must be TXT or TXT2",
            )
        )

    for lineno in range(start, len(lines)):
        line = lines[lineno]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(_WS))
        body = line[indent:]
        keyless = body.startswith("[")
        key_end = 0 if keyless else next((i for i, ch in enumerate(body) if ch in _WS), len(body))
        key = body[:key_end]
        key_span = Span(lineno, indent, lineno, indent + key_end)
        rest_off = indent + key_end
        while rest_off < len(line) and line[rest_off] in _WS:
            rest_off += 1
        rest_off = _skip_equals(line, rest_off) if not keyless else rest_off
        rest = line[rest_off:].rstrip(_WS)

        value: Value | None = None
        value_span: Span | None = None
        # A key never contains "=": the only accepted "=" shape is the
        # `key = "value"` form handled above.
        bad = "=" in key
        if rest and not bad:
            value_span = Span(lineno, rest_off, lineno, rest_off + len(rest))
            if rest[0] == '"':
                close = rest.find('"', 1)
                if close == -1:
                    complete = False
                    value = StringValue(rest[1:], terminated=False)
                    diags.append(
                        _diag(
                            path,
                            value_span,
                            Severity.ERROR,
                            P003,
                            "Unterminated quoted string",
                        )
                    )
                else:
                    value = StringValue(rest[1:close])
                    value_span = Span(lineno, rest_off, lineno, rest_off + close + 1)
                    # Any text after the closing quote (stuck to it or
                    # whitespace separated) makes the line unparseable.
                    bad = bool(rest[close + 1 :].strip())
            elif rest[0] == "[":
                value = _parse_list(rest)
                bad = value is None
            elif rest in ("TRUE", "FALSE"):
                value = BoolValue(rest == "TRUE")
            else:
                value = _number(rest)
                if value is None and _HEX_RE.fullmatch(rest):
                    value = HexValue(rest)
                bad = value is None
        if bad:
            complete = False
            diags.append(
                _diag(
                    path,
                    Span(lineno, indent, lineno, len(line.rstrip(_WS))),
                    Severity.ERROR,
                    P002,
                    f"Line could not be parsed and was skipped: {line.strip()!r}",
                )
            )
            continue

        while stack and stack[-1].indent >= indent:
            stack.pop()
        parent = stack[-1] if stack else None
        end_col = value_span.end_col if value_span else key_span.end_col
        node = Node(
            key=key,
            key_span=key_span,
            value=value,
            value_span=value_span,
            parent=parent,
            extent=Span(lineno, indent, lineno, end_col),
            indent=indent,
        )
        (parent.children if parent else roots).append(node)
        anc = parent
        while anc is not None:
            anc.extent = Span(anc.extent.line, anc.extent.col, lineno, end_col)
            anc = anc.parent
        if value is None:
            stack.append(node)

        if header == "TXT2" and parent is None and key == VERSION_KEY:
            _check_version(node, path, game_version, diags)

    return ParsedFile(header, roots, diags, complete)


def _check_version(
    node: Node,
    path: Path,
    project: GameVersion | None,
    diags: list[Diagnostic],
) -> None:
    """Validate a ``SinsArchiveVersion`` node in a TXT2 file.

    Archive versions are backwards compatible: a known version that is not
    newer than the project is fine. An unknown version, or one newer than the
    project, is informational and the file is validated at the project level.

    Args:
        node: The version node.
        path: File path for Diagnostics.
        project: The project's Game Version, or None to skip the check.
        diags: Diagnostic list to append to.

    Returns:
        None.

    Raises:
        None.
    """
    span = node.value_span or node.key_span
    val = node.value
    if not isinstance(val, NumberValue) or not val.is_integer:
        diags.append(
            _diag(path, span, Severity.ERROR, P004, "SinsArchiveVersion must be an integer")
        )
    elif project is not None:
        level = archive_level(val.value)
        if level is None:
            message = (
                f"SinsArchiveVersion {val.value} is not recognised; validating at {project.value}"
            )
        elif is_newer_than(level, project):
            message = (
                f"SinsArchiveVersion {val.value} is newer than {project.value}; "
                f"validating at {project.value}"
            )
        else:
            return
        diags.append(_diag(path, span, Severity.INFO, P004, message))


def _format_value(value: Value) -> str:
    """Render a value back to file syntax.

    Args:
        value: The value.

    Returns:
        The text form.

    Raises:
        None.
    """
    match value:
        case StringValue(text, terminated):
            return f'"{text}"' if terminated else f'"{text}'
        case NumberValue(raw, _):
            return raw
        case BoolValue(v):
            return "TRUE" if v else "FALSE"
        case HexValue(raw):
            return raw
        case ListValue(items, separator):
            if not items:
                return "[ ]"
            return "[ " + (" , " if separator == "," else " ").join(i.raw for i in items) + " ]"


def format_tree(parsed: ParsedFile) -> str:
    """Render a parsed tree as canonical text (used by tests).

    Nesting is written with one tab per level and keys are separated from
    values by a single space.

    Args:
        parsed: The parsed file.

    Returns:
        The canonical text, ending with a newline.

    Raises:
        None.
    """
    out: list[str] = []
    if parsed.header:
        out.append(parsed.header)

    def walk(nodes: list[Node], depth: int) -> None:
        for n in nodes:
            line = "\t" * depth + n.key
            if n.value is not None:
                line += ("" if not n.key else " ") + _format_value(n.value)
            out.append(line)
            walk(n.children, depth + 1)

    walk(parsed.nodes, 0)
    return "\n".join(out) + "\n"


__all__ = [
    "BoolValue",
    "HexValue",
    "ListValue",
    "Node",
    "NumberValue",
    "ParsedFile",
    "StringValue",
    "Value",
    "format_tree",
    "parse",
    "read_text_file",
]
