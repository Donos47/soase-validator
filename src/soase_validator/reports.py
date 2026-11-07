"""Validation reports shared by the command line and the MCP server.

A report lists only the files that have findings and records how many files
were validated. It is built from the per-file results of the Engine and is
written as JSON or text. This module holds no MCP SDK code.

A result entry counts as a validated file unless it carries a
``SOASE-C050`` Diagnostic: that code marks a file, or a directory, outside
every Mod Root that was not validated. Its Diagnostic is still a finding.
"""

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soase_validator.engine.diagnostics import C050
from soase_validator.engine.model import Diagnostic, Severity

TOP_FILE_LIMIT = 10


@dataclass(frozen=True, slots=True)
class Report:
    """The findings of one validation run.

    Attributes:
        files_validated: Number of result entries that were validated.
        files: Diagnostics in the structured form, per file with findings,
            in result order.
        counts: Number of Diagnostics per severity name.
        by_code: Number of Diagnostics per code, ordered by code.
    """

    files_validated: int
    files: dict[str, list[dict[str, Any]]]
    counts: dict[str, int]
    by_code: dict[str, int]

    @property
    def files_with_findings(self) -> int:
        """Return the number of files that have at least one Diagnostic."""
        return len(self.files)


def diagnostic_to_dict(diagnostic: Diagnostic) -> dict[str, Any]:
    """Convert an Engine Diagnostic to its structured form.

    Args:
        diagnostic: The Engine Diagnostic with zero-based positions.

    Returns:
        A mapping with ``file``, one-based ``line`` and ``column``, the
        one-based end position, ``severity``, ``code`` and ``message``.
    """
    return {
        "file": str(diagnostic.file),
        "line": diagnostic.range.start.line + 1,
        "column": diagnostic.range.start.col + 1,
        "end_line": diagnostic.range.end.line + 1,
        "end_column": diagnostic.range.end.col + 1,
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
    }


def build_report(results: Mapping[Path, Sequence[Diagnostic]]) -> Report:
    """Build a report from per-file validation results.

    Args:
        results: Diagnostics per file, including files with none.

    Returns:
        The report.
    """
    files: dict[str, list[dict[str, Any]]] = {}
    counts = {severity.value: 0 for severity in Severity}
    by_code: dict[str, int] = {}
    validated = 0
    for path, found in results.items():
        if not any(item.code == C050 for item in found):
            validated += 1
        if not found:
            continue
        files[str(path)] = [diagnostic_to_dict(item) for item in found]
        for item in found:
            counts[item.severity.value] += 1
            by_code[item.code] = by_code.get(item.code, 0) + 1
    return Report(validated, files, counts, dict(sorted(by_code.items())))


def report_to_dict(report: Report) -> dict[str, Any]:
    """Convert a report to its JSON layout.

    Args:
        report: The report.

    Returns:
        A mapping with ``files_validated``, ``files_with_findings``,
        ``counts``, ``by_code`` and ``files``.
    """
    return {
        "files_validated": report.files_validated,
        "files_with_findings": report.files_with_findings,
        "counts": dict(report.counts),
        "by_code": dict(report.by_code),
        "files": report.files,
    }


def summary_line(report: Report) -> str:
    """Render the counts of a report as one line.

    Args:
        report: The report.

    Returns:
        Files validated and the error, warning and info counts.
    """
    counts = report.counts
    return (
        f"{report.files_validated} files validated, {counts['error']} errors, "
        f"{counts['warning']} warnings, {counts['info']} info"
    )


def diagnostic_line(item: Mapping[str, Any]) -> str:
    """Render a structured Diagnostic as a text line.

    Args:
        item: A mapping as built by ``diagnostic_to_dict``.

    Returns:
        ``file:line:column: severity code message``.
    """
    return (
        f"{item['file']}:{item['line']}:{item['column']}: "
        f"{item['severity']} {item['code']} {item['message']}"
    )


def format_json(report: Report) -> str:
    """Render a report as JSON text.

    Args:
        report: The report.

    Returns:
        Indented JSON ending in a newline.
    """
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n"


def format_text(report: Report) -> str:
    """Render a report as text.

    Args:
        report: The report.

    Returns:
        One line per Diagnostic, then the summary line.
    """
    lines = [diagnostic_line(item) for found in report.files.values() for item in found]
    lines.append(summary_line(report))
    return "\n".join(lines) + "\n"


def top_files(report: Report, limit: int = TOP_FILE_LIMIT) -> list[dict[str, Any]]:
    """List the files with the most findings.

    Args:
        report: The report.
        limit: Maximum number of entries.

    Returns:
        ``file`` and ``count`` entries, most findings first, ties by path.
    """
    ranked = sorted(report.files.items(), key=lambda entry: (-len(entry[1]), entry[0]))
    return [{"file": file, "count": len(found)} for file, found in ranked[:limit]]


def summary_to_dict(report: Report, path: Path) -> dict[str, Any]:
    """Build the summary returned when a report is written.

    Args:
        report: The report.
        path: Where the report was written.

    Returns:
        The report layout without ``files``, plus ``report`` and ``top_files``.
    """
    summary = report_to_dict(report)
    del summary["files"]
    summary["report"] = str(path)
    summary["top_files"] = top_files(report)
    return summary


def write_report(path: Path, text: str) -> None:
    """Write report text, replacing any existing file atomically.

    The text goes to a temporary file in the target directory first, so a
    failed write leaves an existing report intact.

    Args:
        path: The report file; its directory must exist.
        text: The content, written as UTF-8.

    Raises:
        FileNotFoundError: If the directory of ``path`` does not exist.
        OSError: If writing or replacing fails; the temporary file is removed.
    """
    directory = path.parent
    if not directory.is_dir():
        raise FileNotFoundError(f"directory does not exist: {directory}")
    handle, temp_name = tempfile.mkstemp(dir=directory, prefix=path.name + ".", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_file():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise
