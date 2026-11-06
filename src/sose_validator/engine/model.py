"""Shared data model for Engine results.

All types are frozen dataclasses with ``slots=True``. Positions are zero-based
internally; front ends convert to their own convention (MCP output is
one-based).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A zero-based line and column in a text document.

    Attributes:
        line: Zero-based line number.
        col: Zero-based column (character offset within the line).
    """

    line: int
    col: int


@dataclass(frozen=True, slots=True, order=True)
class Range:
    """A half-open range between two positions, zero-based.

    Attributes:
        start: Inclusive start position.
        end: Exclusive end position.
    """

    start: Position
    end: Position


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """A zero-based source span stored as flat coordinates.

    Attributes:
        line: Zero-based start line.
        col: Zero-based start column.
        end_line: Zero-based end line.
        end_col: Zero-based exclusive end column.
    """

    line: int
    col: int
    end_line: int
    end_col: int

    def to_range(self) -> Range:
        """Convert the span to a ``Range``.

        Returns:
            The equivalent ``Range``.

        Raises:
            None.
        """
        return Range(Position(self.line, self.col), Position(self.end_line, self.end_col))


class Severity(StrEnum):
    """Diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single validation finding.

    Attributes:
        file: Path of the file the finding belongs to.
        range: Zero-based range of the offending text.
        severity: Error, warning or info.
        code: Stable code such as ``SOSE-V020``.
        message: Human-readable message.
        data: Optional payload for quick fixes or Layer information.
    """

    file: Path
    range: Range
    severity: Severity
    code: str
    message: str
    data: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompletionItem:
    """A completion candidate.

    Attributes:
        label: Text shown and inserted.
        kind: One of ``key``, ``enum``, ``reference`` or ``entity_type``.
        detail: Short extra text, for example the providing Layer name.
        documentation: Help text from the Definition, if any.
    """

    label: str
    kind: str
    detail: str | None = None
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class HoverResult:
    """Hover content for a position.

    Attributes:
        contents: Markdown or plain text to display.
        range: Zero-based range the hover applies to, if known.
    """

    contents: str
    range: Range | None = None


@dataclass(frozen=True, slots=True)
class Location:
    """A location in a file, used for go-to-definition.

    Attributes:
        file: Path of the target file.
        range: Zero-based range within the file.
    """

    file: Path
    range: Range


@dataclass(frozen=True, slots=True)
class FieldHelp:
    """Help for a Definition field.

    Attributes:
        structure: Structure name the field belongs to.
        field: Field name.
        validation_type: Validation type of the field value.
        required: Whether the field is required.
        help: Definition help text, if any.
        version_gate: Game Version gate expression, if any.
    """

    structure: str
    field: str
    validation_type: str
    required: bool = False
    help: str | None = None
    version_gate: str | None = None
