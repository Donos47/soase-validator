"""Game versions and version-gate evaluation.

A gate expression is a comma or space separated list of tokens. An element
guarded by a gate is visible for a Game Version when any token is satisfied.
A missing or empty gate allows every version.

Each Game Version has a capability set: the gate tokens it satisfies.
Rebellion 1.96 starts from the Rebellion 194 set. The optional
``definitions/versions.json`` file can add or remove tokens for a version
(``overrides``), flag tokens as ``unverified``, and record audit status.

This module is pure apart from reading the bundled ``versions.json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import cache
from importlib import resources
from typing import Any


class GameVersion(Enum):
    """Game versions the tool understands."""

    VANILLA = "vanilla"
    ENTRENCHMENT = "entrenchment"
    DIPLOMACY = "diplomacy"
    REBELLION_185 = "rebellion-185"
    REBELLION_193 = "rebellion-193"
    REBELLION_194 = "rebellion-194"
    REBELLION_196 = "rebellion-1.96"


#: Version used when a bare "Rebellion" is given.
DEFAULT_REBELLION = GameVersion.REBELLION_196

#: Every gate token the tool recognises.
GATE_TOKENS: frozenset[str] = frozenset(
    {
        "Vanilla",
        "Entrenchment",
        "EntrenchmentOnly",
        "Diplomacy",
        "DiplomacyOnly",
        "Rebellion",
        "NotRebellion",
        "NotDiplomacyOrRebellion",
        "Rebellion185",
        "Rebellion193",
        "Rebellion194",
    }
)

_V = GameVersion
_BASE_CAPABILITIES: dict[GameVersion, frozenset[str]] = {
    _V.VANILLA: frozenset({"Vanilla", "NotRebellion", "NotDiplomacyOrRebellion"}),
    _V.ENTRENCHMENT: frozenset(
        {
            "Entrenchment",
            "EntrenchmentOnly",
            "NotRebellion",
            "NotDiplomacyOrRebellion",
        }
    ),
    _V.DIPLOMACY: frozenset({"Entrenchment", "Diplomacy", "DiplomacyOnly", "NotRebellion"}),
    _V.REBELLION_185: frozenset({"Entrenchment", "Diplomacy", "Rebellion", "Rebellion185"}),
    _V.REBELLION_193: frozenset(
        {"Entrenchment", "Diplomacy", "Rebellion", "Rebellion185", "Rebellion193"}
    ),
    _V.REBELLION_194: frozenset(
        {
            "Entrenchment",
            "Diplomacy",
            "Rebellion",
            "Rebellion185",
            "Rebellion193",
            "Rebellion194",
        }
    ),
}
# Rebellion 1.96 starts from the 194 capability set.
_BASE_CAPABILITIES[_V.REBELLION_196] = _BASE_CAPABILITIES[_V.REBELLION_194]

_SPLIT = re.compile(r"[,\s]+")
_NORMALIZE = re.compile(r"[\s_.\-]+")

_ALIASES: dict[str, GameVersion] = {
    "vanilla": _V.VANILLA,
    "entrenchment": _V.ENTRENCHMENT,
    "diplomacy": _V.DIPLOMACY,
    "rebellion": DEFAULT_REBELLION,
    "rebellion185": _V.REBELLION_185,
    "rebellion193": _V.REBELLION_193,
    "rebellion194": _V.REBELLION_194,
    "rebellion196": _V.REBELLION_196,
    "185": _V.REBELLION_185,
    "193": _V.REBELLION_193,
    "194": _V.REBELLION_194,
    "196": _V.REBELLION_196,
}


@dataclass(frozen=True, slots=True)
class VersionData:
    """Contents of ``definitions/versions.json``.

    Attributes:
        audit_status: Maps a version id (``GameVersion.value``) to its status.
        overrides: Maps a version id to tokens to ``add`` and ``remove``.
        unverified: Gate tokens whose interpretation is not verified.
    """

    audit_status: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    unverified: tuple[str, ...] = ()


def parse_game_version(text: str) -> GameVersion | None:
    """Parse a user-supplied version name.

    A bare "Rebellion" maps to Rebellion 1.96.

    Args:
        text: Name such as ``"rebellion"``, ``"Rebellion 1.96"`` or ``"194"``.

    Returns:
        The matching GameVersion, or None when the name is not recognised.
    """
    return _ALIASES.get(_NORMALIZE.sub("", text.strip().lower()))


def parse_version_data(raw: dict[str, Any]) -> VersionData:
    """Build VersionData from decoded JSON, tolerating missing sections.

    Args:
        raw: Decoded ``versions.json`` content.

    Returns:
        The parsed VersionData.
    """
    overrides: dict[str, dict[str, tuple[str, ...]]] = {}
    for version_id, entry in (raw.get("overrides") or {}).items():
        if not isinstance(entry, dict):
            continue
        overrides[version_id] = {
            "add": tuple(entry.get("add") or ()),
            "remove": tuple(entry.get("remove") or ()),
        }
    return VersionData(
        audit_status=dict(raw.get("audit_status") or {}),
        overrides=overrides,
        unverified=tuple(raw.get("unverified") or ()),
    )


@cache
def load_version_data() -> VersionData:
    """Load the bundled ``definitions/versions.json``.

    Returns:
        The parsed VersionData; empty defaults when the file is absent.

    Raises:
        json.JSONDecodeError: If the bundled file is malformed.
    """
    resource = resources.files("sose_validator.definitions").joinpath("versions.json")
    if not resource.is_file():
        return VersionData()
    return parse_version_data(json.loads(resource.read_text(encoding="utf-8")))


def capabilities(version: GameVersion, data: VersionData | None = None) -> frozenset[str]:
    """Return the gate tokens a Game Version satisfies.

    Args:
        version: The Game Version.
        data: Version data to apply; defaults to the bundled file.

    Returns:
        The capability set after applying any overrides.
    """
    data = load_version_data() if data is None else data
    tokens = set(_BASE_CAPABILITIES[version])
    override = data.overrides.get(version.value)
    if override:
        tokens |= set(override["add"])
        tokens -= set(override["remove"])
    return frozenset(tokens)


def gate_allows(gate: str | None, version: GameVersion, data: VersionData | None = None) -> bool:
    """Decide whether a gate expression is visible for a Game Version.

    Args:
        gate: Comma or space separated tokens. None or empty allows all.
        version: The active Game Version.
        data: Version data to apply; defaults to the bundled file.

    Returns:
        True when the gate is empty or any token is satisfied.
    """
    tokens = [t for t in _SPLIT.split(gate or "") if t]
    if not tokens:
        return True
    caps = capabilities(version, data)
    return any(t in caps for t in tokens)


def audit_status(version: GameVersion, data: VersionData | None = None) -> str:
    """Return the audit status of a Game Version.

    Args:
        version: The Game Version.
        data: Version data to read; defaults to the bundled file.

    Returns:
        ``"audited"`` or ``"unaudited"``.
    """
    data = load_version_data() if data is None else data
    return data.audit_status.get(version.value, "unaudited")


def unverified_tokens(data: VersionData | None = None) -> tuple[str, ...]:
    """Return gate tokens flagged as unverified.

    Args:
        data: Version data to read; defaults to the bundled file.

    Returns:
        The unverified token names.
    """
    data = load_version_data() if data is None else data
    return data.unverified
