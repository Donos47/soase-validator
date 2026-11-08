"""Stable Diagnostic code catalogue and code filtering.

Code families: ``P`` parser, ``V`` validator, ``R`` reference, ``C``
chain/config, ``M`` manifest, ``D`` definition load, ``X`` internal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from soase_validator.engine.model import Diagnostic, Severity


@dataclass(frozen=True, slots=True)
class CodeInfo:
    """Catalogue entry for a Diagnostic code.

    Attributes:
        code: Stable code such as ``SOASE-V020``.
        family: Family letter (P, V, R, C, M, D or X).
        severity: Default severity.
        summary: Short description of the condition.
    """

    code: str
    family: str
    severity: Severity
    summary: str


# Parser codes.
P001 = "SOASE-P001"
P002 = "SOASE-P002"
P003 = "SOASE-P003"
P004 = "SOASE-P004"
# Validator codes.
V010 = "SOASE-V010"
V020 = "SOASE-V020"
V030 = "SOASE-V030"
V040 = "SOASE-V040"
V050 = "SOASE-V050"
V060 = "SOASE-V060"
V070 = "SOASE-V070"
V080 = "SOASE-V080"
# Reference codes.
R010 = "SOASE-R010"
# Chain and configuration codes.
C010 = "SOASE-C010"
C020 = "SOASE-C020"
C030 = "SOASE-C030"
C040 = "SOASE-C040"
C050 = "SOASE-C050"
# Manifest codes.
M010 = "SOASE-M010"
M020 = "SOASE-M020"
M030 = "SOASE-M030"
M040 = "SOASE-M040"
# Definition load codes.
D001 = "SOASE-D001"
# Internal codes.
X001 = "SOASE-X001"


def _info(code: str, severity: Severity, summary: str) -> CodeInfo:
    """Build a catalogue entry, deriving the family from the code.

    Args:
        code: Full code string.
        severity: Default severity.
        summary: Short description.

    Returns:
        The catalogue entry.

    Raises:
        None.
    """
    return CodeInfo(code, code.removeprefix("SOASE-")[0], severity, summary)


CODE_CATALOGUE: dict[str, CodeInfo] = {
    info.code: info
    for info in (
        _info(P001, Severity.ERROR, "Missing or invalid file header (TXT or TXT2)"),
        _info(P002, Severity.ERROR, "Line could not be parsed and was skipped"),
        _info(P003, Severity.ERROR, "Unterminated quoted string"),
        _info(P004, Severity.INFO, "Unrecognised SinsArchiveVersion for the game version"),
        _info(V010, Severity.ERROR, "Unknown entityType for the game version"),
        _info(V020, Severity.ERROR, "Unknown key for the structure"),
        _info(V030, Severity.ERROR, "Iterative count mismatch or limit exceeded"),
        _info(V040, Severity.ERROR, "Required field missing"),
        _info(V050, Severity.ERROR, "Invalid value for the field"),
        _info(V060, Severity.ERROR, "Key out of the declared order"),
        _info(V070, Severity.ERROR, "Duplicate key in a block"),
        _info(V080, Severity.INFO, "Unexpected indentation"),
        _info(R010, Severity.ERROR, "Unresolved reference"),
        _info(C010, Severity.ERROR, "Layer chain cycle"),
        _info(C020, Severity.WARNING, "Layer missing or unusable"),
        _info(C030, Severity.INFO, "Reference checks limited by missing Layers"),
        _info(C040, Severity.INFO, "Project file overrides a file of a lower Layer"),
        _info(C050, Severity.WARNING, "File is outside every Mod Root; it was not validated"),
        _info(M010, Severity.ERROR, "File not listed in governing manifest"),
        _info(M020, Severity.INFO, "Manifest entry matches no file in any Layer"),
        _info(M030, Severity.ERROR, "Manifest count differs from the listed names"),
        _info(M040, Severity.INFO, "Duplicate manifest entry"),
        _info(D001, Severity.WARNING, "Definition load problem"),
        _info(X001, Severity.ERROR, "Internal error; results may be partial"),
    )
}


def filter_disabled(
    diagnostics: Iterable[Diagnostic],
    disabled_codes: Iterable[str],
) -> list[Diagnostic]:
    """Remove Diagnostics whose code is disabled.

    Order of the remaining Diagnostics is preserved. Codes are compared
    case-insensitively.

    Args:
        diagnostics: Diagnostics to filter.
        disabled_codes: Codes to remove, such as ``SOASE-C030``.

    Returns:
        A new list containing only Diagnostics whose code is not disabled.

    Raises:
        None.
    """
    disabled = {code.upper() for code in disabled_codes}
    return [d for d in diagnostics if d.code.upper() not in disabled]
