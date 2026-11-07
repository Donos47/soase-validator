"""Manifest rules, parsing and formatting.

A manifest is a ``TXT`` file with a count line followed by one quoted name
per line. The key names, and whether names carry a file extension, are per
manifest type and come from the bundled ``manifest_rules.json``. Names are
compared ignoring case.

Parsing keeps the original text of every line so that formatting an
unchanged :class:`ManifestData` returns the input exactly.

:func:`manifest_check` compares the manifests of a Chain with its files. The
governing manifest of a type is the one in the highest Layer that has it. Only
manifests and files of Project Layers are reported on; lower Layers are read
for context. Parsing and formatting are pure apart from reading the bundled
rules.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path, PurePath

from soase_validator.engine.config import ManifestPrefs
from soase_validator.engine.diagnostics import M010, M020, M030, M040
from soase_validator.engine.model import Diagnostic, Position, Range, Severity
from soase_validator.engine.parser import Node, StringValue, parse
from soase_validator.engine.refindex import (
    FILE_REFERENCE_RULES,
    FileSystem,
    LayerIndex,
    RealFileSystem,
    RefKind,
)

MANIFEST_SUFFIX = ".manifest"

DEFAULT_HEADER = "TXT"
DEFAULT_EOL = "\r\n"

_HEADERS = ("TXT", "TXT2")
_SKYBOX_DATA_EXTENSION = ".skyboxbackdropdata"
_SKYBOX_MESH_KEY = "meshName"
_LINE_SPLIT = re.compile(r"\r\n|\n|\r")
_LINE_PARTS = re.compile(r"([^\r\n]*)(\r\n|\n|\r|\Z)")
_COUNT_VALUE = re.compile(r"[ \t]+(\d+)[ \t]*")
_NAME_VALUE = re.compile(r'[ \t]+"([^"]*)"[ \t]*')


@dataclass(frozen=True, slots=True)
class ManifestRule:
    """Per-type rules for one manifest file.

    Attributes:
        manifest: Manifest file name, for example ``entity.manifest``.
        count_key: Key of the count line.
        name_key: Key of each name line.
        includes_extension: Whether listed names carry the file extension.
        example: Example of a listed name.
        directory: Directory of the governed files, when the rule states one.
        extensions: Extensions of the governed files, including the dot.
        identified_by: How a governed subset is identified, when the rule
            governs only a subset of a file type.
        unlisted_by_base_game: Names the base game leaves unlisted.
        never_governed: File names, with extension and without directories,
            that the manifest does not govern in any Layer.
    """

    manifest: str
    count_key: str
    name_key: str
    includes_extension: bool
    example: str
    directory: str | None = None
    extensions: tuple[str, ...] = ()
    identified_by: str | None = None
    unlisted_by_base_game: tuple[str, ...] = ()
    never_governed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One listed name.

    Attributes:
        name: The name between the quotes.
        line: Zero-based line number in the manifest text.
        raw: The line text without its line ending.
    """

    name: str
    line: int
    raw: str

    @property
    def key(self) -> str:
        """The casefolded name used for matching."""
        return self.name.casefold()


@dataclass(frozen=True, slots=True)
class ManifestProblem:
    """A line that could not be read as part of a manifest.

    Attributes:
        line: Zero-based line number.
        message: What is wrong with the line.
    """

    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ManifestData:
    """A parsed manifest.

    Attributes:
        header: ``"TXT"`` or ``"TXT2"``, or None when the first line is not
            a header.
        eol: Line ending of the text: CRLF or LF.
        final_newline: Whether the text ends with a line ending.
        count: Value of the count line, or None when absent or unreadable.
        count_line: Zero-based line number of the count line, or None.
        count_raw: Original text of the count line, or None.
        entries: Listed names in file order.
        problems: Lines that were skipped, with reasons.
    """

    header: str | None
    eol: str
    final_newline: bool
    count: int | None
    count_line: int | None
    count_raw: str | None
    entries: tuple[ManifestEntry, ...]
    problems: tuple[ManifestProblem, ...] = field(default=())

    @property
    def names(self) -> tuple[str, ...]:
        """Listed names in file order."""
        return tuple(entry.name for entry in self.entries)

    @property
    def keys(self) -> frozenset[str]:
        """Casefolded listed names."""
        return frozenset(entry.key for entry in self.entries)

    def lists(self, name: str) -> bool:
        """Tell whether a name is listed, ignoring case.

        Args:
            name: The name as written in the manifest, so with the extension
                exactly when the rule's names include it.

        Returns:
            True when an entry matches.
        """
        return name.casefold() in self.keys


@cache
def load_manifest_rules() -> dict[str, ManifestRule]:
    """Load the bundled manifest rules.

    Returns:
        Rules keyed by casefolded manifest file name.

    Raises:
        ValueError: If the bundled file is malformed.
    """
    text = (
        resources.files("soase_validator.definitions")
        .joinpath("manifest_rules.json")
        .read_text(encoding="utf-8")
    )
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("manifest_rules.json must hold an object")
    rules: dict[str, ManifestRule] = {}
    for manifest, body in raw.items():
        rules[manifest.casefold()] = _build_rule(manifest, body)
    return rules


def rule_for(manifest: str) -> ManifestRule | None:
    """Find the rule for a manifest file name, ignoring case.

    Args:
        manifest: A manifest file name or path.

    Returns:
        The rule, or None for an unknown manifest type.
    """
    return load_manifest_rules().get(PurePath(manifest).name.casefold())


def listed_name(rule: ManifestRule, file_name: str) -> str:
    """Compute the name under which a file is listed.

    Args:
        rule: The manifest rule.
        file_name: The file name with its extension, without directories.

    Returns:
        The file name, minus its extension when the rule's names carry none.
    """
    if rule.includes_extension:
        return file_name
    return PurePath(file_name).stem


def parse_manifest(text: str, rule: ManifestRule) -> ManifestData:
    """Parse manifest text.

    Never raises: lines that do not fit the rule are skipped and reported in
    ``problems``. Blank lines are ignored.

    Args:
        text: The manifest text.
        rule: The rule for the manifest type.

    Returns:
        The parsed manifest.
    """
    eol = _detect_eol(text)
    final_newline = bool(text) and text.endswith(("\n", "\r"))
    lines = _LINE_SPLIT.split(text)
    if final_newline:
        lines.pop()

    header: str | None = None
    count: int | None = None
    count_line: int | None = None
    count_raw: str | None = None
    entries: list[ManifestEntry] = []
    problems: list[ManifestProblem] = []

    for number, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            continue
        if number == 0 and stripped in _HEADERS:
            header = stripped
            continue
        if number == 0:
            problems.append(ManifestProblem(0, "Missing file header: expected TXT or TXT2"))
        count_match = _match_key(raw, rule.count_key, _COUNT_VALUE)
        if count_match is not None:
            if count_line is not None:
                problems.append(ManifestProblem(number, "Repeated count line"))
                continue
            count = int(count_match.group(1))
            count_line = number
            count_raw = raw
            continue
        name_match = _match_key(raw, rule.name_key, _NAME_VALUE)
        if name_match is not None:
            entries.append(ManifestEntry(name_match.group(1), number, raw))
            continue
        problems.append(
            ManifestProblem(
                number,
                f"Expected {rule.count_key} or {rule.name_key} line, found {stripped!r}",
            )
        )

    if count_line is None:
        problems.append(ManifestProblem(1, f"Missing {rule.count_key} line"))

    return ManifestData(
        header=header,
        eol=eol,
        final_newline=final_newline,
        count=count,
        count_line=count_line,
        count_raw=count_raw,
        entries=tuple(entries),
        problems=tuple(problems),
    )


def format_manifest(data: ManifestData, rule: ManifestRule) -> str:
    """Render a manifest as text.

    Lines read by :func:`parse_manifest` are written back as read. A count
    line that was absent is written from the number of entries.

    Args:
        data: The manifest.
        rule: The rule for the manifest type.

    Returns:
        The manifest text with ``data.eol`` line endings.
    """
    lines = [data.header or DEFAULT_HEADER]
    lines.append(
        data.count_raw
        if data.count_raw is not None
        else f"{rule.count_key} {data.count if data.count is not None else len(data.entries)}"
    )
    lines.extend(entry.raw for entry in data.entries)
    text = data.eol.join(lines)
    return text + data.eol if data.final_newline else text


def build_manifest(
    rule: ManifestRule,
    names: list[str] | tuple[str, ...],
    *,
    header: str = DEFAULT_HEADER,
    eol: str = DEFAULT_EOL,
) -> ManifestData:
    """Build a manifest whose count matches its names.

    Args:
        rule: The rule for the manifest type.
        names: Names to list, in order.
        header: ``"TXT"`` or ``"TXT2"``.
        eol: Line ending to use.

    Returns:
        A manifest ending with a line ending.

    Raises:
        ValueError: If the header is not ``TXT`` or ``TXT2``.
    """
    if header not in _HEADERS:
        raise ValueError(f"header must be one of {', '.join(_HEADERS)}")
    entries = tuple(
        ManifestEntry(name, number, name_line(rule, name))
        for number, name in enumerate(names, start=2)
    )
    return ManifestData(
        header=header,
        eol=eol,
        final_newline=True,
        count=len(entries),
        count_line=1,
        count_raw=count_line_text(rule, len(entries)),
        entries=entries,
    )


def count_line_text(rule: ManifestRule, count: int) -> str:
    """Render a count line.

    Args:
        rule: The rule for the manifest type.
        count: The count to write.

    Returns:
        The line without a line ending.
    """
    return f"{rule.count_key} {count}"


def name_line(rule: ManifestRule, name: str) -> str:
    """Render a name line.

    Args:
        rule: The rule for the manifest type.
        name: The name to list.

    Returns:
        The line without a line ending.
    """
    return f'{rule.name_key} "{name}"'


def _detect_eol(text: str) -> str:
    """Detect the line ending of a text.

    Args:
        text: The manifest text.

    Returns:
        LF when the first line ending is a bare line feed, otherwise CRLF.
    """
    index = text.find("\n")
    if index > 0 and text[index - 1] != "\r":
        return "\n"
    return DEFAULT_EOL


def _match_key(line: str, key: str, value: re.Pattern[str]) -> re.Match[str] | None:
    """Match a ``key value`` line for an exact key.

    Args:
        line: The line text.
        key: The expected key.
        value: Pattern for the text after the key.

    Returns:
        The match of the value part, or None.
    """
    if not line.startswith(key):
        return None
    return value.fullmatch(line, len(key))


def _build_rule(manifest: str, body: object) -> ManifestRule:
    """Build a rule from its JSON object.

    Args:
        manifest: Manifest file name.
        body: The decoded JSON object.

    Returns:
        The rule.

    Raises:
        ValueError: If a required field is missing or has the wrong type.
    """
    if not isinstance(body, dict):
        raise ValueError(f"manifest rule {manifest} must be an object")
    try:
        governs = body.get("governs", {})
        extensions = governs.get("extensions", [])
        return ManifestRule(
            manifest=manifest,
            count_key=str(body["countKey"]),
            name_key=str(body["nameKey"]),
            includes_extension=bool(body["includesExtension"]),
            example=str(body["example"]),
            directory=governs.get("directory"),
            extensions=tuple(str(ext) for ext in extensions),
            identified_by=governs.get("identifiedBy"),
            unlisted_by_base_game=tuple(str(n) for n in body.get("unlistedByBaseGame", [])),
            never_governed=tuple(str(n) for n in body.get("neverGoverned", [])),
        )
    except (KeyError, AttributeError, TypeError) as exc:
        raise ValueError(f"manifest rule {manifest} is malformed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class GoverningManifest:
    """The manifest the game reads for one manifest type.

    Attributes:
        rule: The rule for the type.
        index: Index of the Layer that owns the manifest.
        position: Position of that Layer in the Chain, lowest first.
        path: Path of the manifest file.
        data: The parsed manifest.
    """

    rule: ManifestRule
    index: LayerIndex
    position: int
    path: Path
    data: ManifestData


def governing_manifest(
    indexes: Sequence[LayerIndex],
    rule: ManifestRule,
    fs: FileSystem | None = None,
) -> GoverningManifest | None:
    """Select the manifest of the highest Layer that provides a type.

    Args:
        indexes: Layer indexes, lowest first.
        rule: The rule for the manifest type.
        fs: The file system; defaults to the real one.

    Returns:
        The manifest, or None when no Layer provides the type or the
        providing file cannot be read.
    """
    fs = RealFileSystem() if fs is None else fs
    key = rule.manifest.casefold()
    for position in range(len(indexes) - 1, -1, -1):
        path = indexes[position].files.get(key)
        if path is None:
            continue
        text = fs.read_text(path)
        if text is None:
            return None
        return GoverningManifest(
            rule, indexes[position], position, path, parse_manifest(text, rule)
        )
    return None


def governed_files(
    index: LayerIndex,
    rule: ManifestRule,
    skybox_meshes: frozenset[str] = frozenset(),
) -> list[Path]:
    """List the files of one Layer that a manifest type governs.

    A file is governed when it has one of the rule's extensions and lies
    directly in the rule's directory, or anywhere in the indexed scope when
    the rule states no directory. A rule that identifies its subset by
    another file type governs the meshes named by that type's values.

    Args:
        index: The Layer index.
        rule: The rule for the manifest type.
        skybox_meshes: Casefolded mesh names from the Chain's
            ``.skyboxbackdropdata`` files; used by rules that identify
            their subset that way.

    Returns:
        The governed files, sorted by path.
    """
    if rule.identified_by is not None:
        mesh = FILE_REFERENCE_RULES[RefKind.MESH]
        found = [
            path
            for key, path in index.files.items()
            if key.startswith(f"{mesh.directory.casefold()}/")
            and key.count("/") == 1
            and key.endswith(mesh.extensions)
            and PurePath(key).stem in skybox_meshes
        ]
        return sorted(found)
    wanted = tuple(ext.casefold() for ext in rule.extensions)
    directory = rule.directory.casefold() if rule.directory else None
    found = []
    for key, path in index.files.items():
        if not key.endswith(wanted):
            continue
        parts = key.split("/")
        if directory is None or (len(parts) == 2 and parts[0] == directory):
            found.append(path)
    return sorted(found)


def skybox_mesh_names(
    indexes: Sequence[LayerIndex], fs: FileSystem | None = None
) -> frozenset[str]:
    """Collect the mesh names that ``.skyboxbackdropdata`` files declare.

    A file in a higher Layer replaces a file of the same path in a lower one.

    Args:
        indexes: Layer indexes, lowest first.
        fs: The file system; defaults to the real one.

    Returns:
        The casefolded ``meshName`` values.
    """
    fs = RealFileSystem() if fs is None else fs
    winners: dict[str, Path] = {}
    for index in indexes:
        for key, path in index.files.items():
            if key.endswith(_SKYBOX_DATA_EXTENSION):
                winners[key] = path
    names: set[str] = set()
    for path in winners.values():
        text = fs.read_text(path)
        if text is not None:
            _collect_values(parse(text, path).nodes, _SKYBOX_MESH_KEY, names)
    return frozenset(names)


def manifest_check(
    indexes: Sequence[LayerIndex],
    prefs: ManifestPrefs | None = None,
    fs: FileSystem | None = None,
) -> list[Diagnostic]:
    """Check the manifests and files of a Chain.

    Reports ``SOASE-M010`` on Project files that a governing manifest does
    not list, and ``SOASE-M020``, ``SOASE-M030`` and ``SOASE-M040`` on the
    manifests the Project owns. A manifest type that no Layer provides is
    not checked.

    Args:
        indexes: Layer indexes, lowest first, with the Project Layers of
            kind ``project``.
        prefs: Manifest preferences; defaults apply when omitted.
        fs: The file system; defaults to the real one.

    Returns:
        The Diagnostics, grouped by manifest type in rule order.
    """
    prefs = ManifestPrefs() if prefs is None else prefs
    fs = RealFileSystem() if fs is None else fs
    skybox = skybox_mesh_names(indexes, fs)
    result: list[Diagnostic] = []
    for rule in load_manifest_rules().values():
        governing = governing_manifest(indexes, rule, fs)
        if governing is None:
            continue
        result.extend(_unlisted_files(indexes, governing, skybox, prefs))
        for position, index in enumerate(indexes):
            if index.layer.kind == "project":
                owned = _owned_manifest(governing, index, position, fs)
                if owned is not None:
                    result.extend(_manifest_hygiene(indexes, owned, prefs))
    return result


def _owned_manifest(
    governing: GoverningManifest, index: LayerIndex, position: int, fs: FileSystem
) -> GoverningManifest | None:
    """Read the manifest of a type that a given Project Layer owns.

    Args:
        governing: The governing manifest, which may be this Layer's own.
        index: The Project Layer index.
        position: Position of the Layer in the Chain.
        fs: The file system.

    Returns:
        The Layer's own manifest, or None when the Layer has none.
    """
    if governing.position == position:
        return governing
    path = index.files.get(governing.rule.manifest.casefold())
    if path is None:
        return None
    text = fs.read_text(path)
    if text is None:
        return None
    return GoverningManifest(
        governing.rule, index, position, path, parse_manifest(text, governing.rule)
    )


def _unlisted_files(
    indexes: Sequence[LayerIndex],
    governing: GoverningManifest,
    skybox: frozenset[str],
    prefs: ManifestPrefs,
) -> list[Diagnostic]:
    """Report Project files that the governing manifest does not list.

    Args:
        indexes: Layer indexes, lowest first.
        governing: The governing manifest.
        skybox: Casefolded skybox mesh names.
        prefs: Manifest preferences.

    Returns:
        One ``SOASE-M010`` Diagnostic per unlisted file.
    """
    rule = governing.rule
    owner = governing.index.layer
    found: list[Diagnostic] = []
    for position, path, name in _unlisted(indexes, governing, skybox, prefs):
        lower = governing.position < position
        message = (
            f"{path.name} is not listed in {rule.manifest} of Layer {owner.name}. "
            "The game will not load the file and may fail to start."
        )
        if lower:
            message += f" Add the entry to {owner.name}'s manifest."
        data = {
            "manifest": str(governing.path),
            "layer": owner.name,
            "name": name,
            "lowerLayer": lower,
        }
        start = Position(0, 0)
        found.append(Diagnostic(path, Range(start, start), Severity.ERROR, M010, message, data))
    return found


def _unlisted(
    indexes: Sequence[LayerIndex],
    governing: GoverningManifest,
    skybox: frozenset[str],
    prefs: ManifestPrefs,
) -> list[tuple[int, Path, str]]:
    """Find Project files that the governing manifest should list but does not.

    Files the manifest never governs, files the base game leaves unlisted
    and files matching an exemption pattern are left out.

    Args:
        indexes: Layer indexes, lowest first.
        governing: The governing manifest.
        skybox: Casefolded skybox mesh names.
        prefs: Manifest preferences.

    Returns:
        ``(position, path, listed name)`` per file, in Chain order.
    """
    rule = governing.rule
    base_game = {name.casefold() for name in rule.unlisted_by_base_game}
    ungoverned = {name.casefold() for name in rule.never_governed}
    found: list[tuple[int, Path, str]] = []
    for position, index in enumerate(indexes):
        if index.layer.kind != "project":
            continue
        for path in governed_files(index, rule, skybox):
            if path.name.casefold() in ungoverned:
                continue
            name = listed_name(rule, path.name)
            if governing.data.lists(name) or name.casefold() in base_game:
                continue
            if _exempt(prefs.exempt_unlisted, name, path.name):
                continue
            found.append((position, path, name))
    return found


def _manifest_hygiene(
    indexes: Sequence[LayerIndex], owned: GoverningManifest, prefs: ManifestPrefs
) -> list[Diagnostic]:
    """Check one Project manifest for count, duplicate and dangling entries.

    Args:
        indexes: Layer indexes, lowest first.
        owned: The Project's manifest.
        prefs: Manifest preferences.

    Returns:
        ``SOASE-M030``, ``SOASE-M040`` and ``SOASE-M020`` Diagnostics.
    """
    data = owned.data
    rule = owned.rule
    found: list[Diagnostic] = []
    count_differs = data.count is not None and data.count != len(data.entries)
    if count_differs and data.count_line is not None:
        message = (
            f"{rule.count_key} is {data.count} but {rule.manifest} lists {len(data.entries)} names."
        )
        found.append(_line_diagnostic(owned, data.count_line, data.count_raw or "", M030, message))
    first_seen: dict[str, ManifestEntry] = {}
    for entry in data.entries:
        earlier = first_seen.setdefault(entry.key, entry)
        if earlier is not entry:
            message = (
                f"{entry.name} is listed more than once in {rule.manifest}; "
                f"first listed on line {earlier.line + 1}."
            )
            found.append(
                _line_diagnostic(owned, entry.line, entry.raw, M040, message, Severity.INFO)
            )
        elif not _exempt(prefs.exempt_unreferenced, entry.name) and not _resolves(
            indexes, rule, entry.name
        ):
            message = f"{entry.name} listed in {rule.manifest} matches no file in any Layer."
            found.append(
                _line_diagnostic(
                    owned, entry.line, entry.raw, M020, message, prefs.unreferenced_severity
                )
            )
    return found


def _line_diagnostic(
    owned: GoverningManifest,
    line: int,
    raw: str,
    code: str,
    message: str,
    severity: Severity = Severity.ERROR,
) -> Diagnostic:
    """Build a Diagnostic that covers one manifest line.

    Args:
        owned: The manifest.
        line: Zero-based line number.
        raw: The line text.
        code: Diagnostic code.
        message: Message text.
        severity: Severity.

    Returns:
        The Diagnostic.
    """
    span = Range(Position(line, 0), Position(line, len(raw)))
    return Diagnostic(owned.path, span, severity, code, message)


def _resolves(indexes: Sequence[LayerIndex], rule: ManifestRule, name: str) -> bool:
    """Tell whether a listed name has a file in any Layer.

    Args:
        indexes: Layer indexes.
        rule: The rule for the manifest type.
        name: The listed name.

    Returns:
        True when a file the rule governs, or for a subset rule the mesh
        file, exists in some Layer.
    """
    if rule.identified_by is not None:
        directory: str | None = FILE_REFERENCE_RULES[RefKind.MESH].directory.casefold()
        candidates = [name.casefold()]
    else:
        directory = rule.directory.casefold() if rule.directory else None
        suffixes = [""] if rule.includes_extension else [e.casefold() for e in rule.extensions]
        candidates = [name.casefold() + suffix for suffix in suffixes]
    for index in indexes:
        for candidate in candidates:
            if directory is not None:
                if f"{directory}/{candidate}" in index.files:
                    return True
            elif any(key.rsplit("/", 1)[-1] == candidate for key in index.files):
                return True
    return False


def _exempt(patterns: Iterable[str], *names: str) -> bool:
    """Tell whether any name matches an exemption pattern.

    Args:
        patterns: Shell-style patterns, compared ignoring case.
        names: Names to test.

    Returns:
        True when a pattern matches a name.
    """
    return any(
        fnmatch.fnmatchcase(name.casefold(), pattern.casefold())
        for pattern in patterns
        for name in names
    )


@dataclass(frozen=True, slots=True)
class ManifestEdit:
    """A planned change to one Project manifest.

    Attributes:
        manifest_path: Path of the manifest.
        original_text: The text the plan was computed from.
        new_text: The text after the change.
        added: Names appended, in order.
        removed: Listed names removed.
    """

    manifest_path: Path
    original_text: str
    new_text: str
    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LowerLayerAdvisory:
    """Entries that the manifest of a lower Layer needs.

    Attributes:
        manifest_path: Path of the lower Layer's manifest.
        manifest: Manifest file name.
        layer_name: Name of the Layer that owns the manifest.
        names: Names to add to that manifest, in the form it lists them.
    """

    manifest_path: Path
    manifest: str
    layer_name: str
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """The outcome of planning a manifest sync.

    Attributes:
        edits: Changes to manifests within the Project.
        advisories: Entries needed by manifests of lower Layers, which are
            never edited.
    """

    edits: tuple[ManifestEdit, ...] = ()
    advisories: tuple[LowerLayerAdvisory, ...] = ()


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """A backup written before a manifest was replaced.

    Attributes:
        manifest_path: Path of the manifest that was written.
        backup_path: Path of its backup copy.
    """

    manifest_path: Path
    backup_path: Path


def plan_sync(
    manifest_text: str,
    rule: ManifestRule,
    missing: Sequence[str],
    remove: Sequence[str] = (),
) -> str:
    """Compute the text of a manifest after adding and removing names.

    Every other line keeps its text and line ending, entries keep their
    order, and only the count line is rewritten, to the number of listed
    names. New names follow the last entry. A name already listed is not
    added again, and a name in both arguments is left alone.

    Args:
        manifest_text: The current manifest text.
        rule: The rule for the manifest type.
        missing: Names to append, in the form the manifest lists them.
        remove: Names to remove, ignoring case; every entry with such a
            name is removed.

    Returns:
        The new text, equal to the input when nothing changes.
    """
    data = parse_manifest(manifest_text, rule)
    removing = {name.casefold() for name in remove} - {name.casefold() for name in missing}
    listed = {key for key in data.keys if key not in removing}
    additions: list[str] = []
    for name in missing:
        if name.casefold() not in listed:
            listed.add(name.casefold())
            additions.append(name)
    kept = [entry for entry in data.entries if entry.key not in removing]
    if not additions and len(kept) == len(data.entries):
        return manifest_text

    segments = _split_lines(manifest_text)
    drop = {entry.line for entry in data.entries if entry.key in removing}
    count_text = count_line_text(rule, len(kept) + len(additions))
    kept_lines = {entry.line for entry in kept}
    out: list[tuple[str, str]] = []
    last_entry = -1
    count_index = -1
    for number, (content, term) in enumerate(segments):
        if number in drop:
            continue
        if number == data.count_line:
            content = count_text
            count_index = len(out)
        out.append((content, term))
        if number in kept_lines:
            last_entry = len(out) - 1

    if data.count_line is None:
        count_index = 1 if data.header is not None else 0
        out.insert(count_index, (count_text, data.eol))
        if last_entry >= count_index:
            last_entry += 1
    if last_entry < 0:
        last_entry = count_index if count_index >= 0 else _last_content_index(out)

    new_lines = [name_line(rule, name) for name in additions]
    if new_lines:
        content, term = out[last_entry]
        at_end = last_entry == len(out) - 1
        out[last_entry] = (content, term or data.eol)
        inserted = [(line, data.eol) for line in new_lines]
        if at_end and not term and out:
            inserted[-1] = (inserted[-1][0], "")
        out[last_entry + 1 : last_entry + 1] = inserted
    return "".join(content + term for content, term in out)


def plan_manifests(
    indexes: Sequence[LayerIndex],
    prefs: ManifestPrefs | None = None,
    fs: FileSystem | None = None,
    *,
    remove_stale: bool = False,
) -> SyncPlan:
    """Plan the sync of every manifest type of a Chain.

    For each manifest type with a governing manifest, the Project files it
    does not list are added. A governing manifest in a Project Layer becomes
    an edit; one in a lower Layer becomes an advisory. A type that no Layer
    provides is skipped, so an overlay without manifests is left alone.

    Args:
        indexes: Layer indexes, lowest first, with the Project Layers of
            kind ``project``.
        prefs: Manifest preferences; defaults apply when omitted.
        fs: The file system; defaults to the real one.
        remove_stale: Also remove entries of Project manifests that match no
            file in any Layer. Names matching an exemption pattern for
            unreferenced entries are kept.

    Returns:
        The plan.
    """
    prefs = ManifestPrefs() if prefs is None else prefs
    fs = RealFileSystem() if fs is None else fs
    skybox = skybox_mesh_names(indexes, fs)
    edits: list[ManifestEdit] = []
    advisories: list[LowerLayerAdvisory] = []
    for rule in load_manifest_rules().values():
        governing = governing_manifest(indexes, rule, fs)
        if governing is None:
            continue
        names: dict[str, str] = {}
        for _position, _path, name in _unlisted(indexes, governing, skybox, prefs):
            names.setdefault(name.casefold(), name)
        added = tuple(names.values())
        owner = governing.index.layer
        if owner.kind != "project":
            if added:
                advisories.append(
                    LowerLayerAdvisory(governing.path, rule.manifest, owner.name, added)
                )
            continue
        stale: tuple[str, ...] = ()
        if remove_stale:
            stale = tuple(
                dict.fromkeys(
                    entry.name
                    for entry in governing.data.entries
                    if not _exempt(prefs.exempt_unreferenced, entry.name)
                    and not _resolves(indexes, rule, entry.name)
                )
            )
        text = fs.read_text(governing.path)
        if text is None:
            continue
        new_text = plan_sync(text, rule, added, stale)
        if new_text != text:
            edits.append(ManifestEdit(governing.path, text, new_text, added, stale))
    return SyncPlan(tuple(edits), tuple(advisories))


def format_plan(plan: SyncPlan) -> str:
    """Render a plan as a unified diff followed by lower-Layer advisories.

    Args:
        plan: The plan.

    Returns:
        Text for a dry run; empty when the plan holds nothing.
    """
    parts: list[str] = []
    for edit in plan.edits:
        parts.extend(
            difflib.unified_diff(
                edit.original_text.splitlines(keepends=True),
                edit.new_text.splitlines(keepends=True),
                fromfile=f"{edit.manifest_path.name} (current)",
                tofile=f"{edit.manifest_path.name} (planned)",
            )
        )
        if parts and not parts[-1].endswith("\n"):
            parts[-1] += "\n"
    for advisory in plan.advisories:
        parts.append(
            f"Layer {advisory.layer_name} owns {advisory.manifest} "
            f"({advisory.manifest_path}); it needs these entries:\n"
        )
        parts.extend(f"  {name}\n" for name in advisory.names)
    return "".join(parts)


def _split_lines(text: str) -> list[tuple[str, str]]:
    """Split text into lines paired with their own line endings.

    Args:
        text: The text.

    Returns:
        ``(content, terminator)`` pairs; the last terminator is empty when
        the text does not end with a line ending.
    """
    return [(m.group(1), m.group(2)) for m in _LINE_PARTS.finditer(text) if m.group(0)]


def _last_content_index(lines: list[tuple[str, str]]) -> int:
    """Find the last line that is not blank.

    Args:
        lines: Lines with their terminators.

    Returns:
        The index, or ``len(lines) - 1`` when every line is blank.
    """
    for index in range(len(lines) - 1, -1, -1):
        if lines[index][0].strip():
            return index
    return len(lines) - 1


def _collect_values(nodes: Iterable[Node], key: str, out: set[str]) -> None:
    """Gather the string values of a key at any depth.

    Args:
        nodes: Nodes to search.
        key: The key to collect.
        out: Set that receives the casefolded values.
    """
    for node in nodes:
        if node.key == key and isinstance(node.value, StringValue):
            out.add(node.value.text.casefold())
        _collect_values(node.children, key, out)


__all__ = [
    "DEFAULT_EOL",
    "DEFAULT_HEADER",
    "MANIFEST_SUFFIX",
    "BackupRecord",
    "GoverningManifest",
    "LowerLayerAdvisory",
    "ManifestData",
    "ManifestEdit",
    "ManifestEntry",
    "ManifestProblem",
    "ManifestRule",
    "SyncPlan",
    "build_manifest",
    "count_line_text",
    "format_manifest",
    "format_plan",
    "governed_files",
    "governing_manifest",
    "listed_name",
    "load_manifest_rules",
    "manifest_check",
    "name_line",
    "parse_manifest",
    "plan_manifests",
    "plan_sync",
    "rule_for",
    "skybox_mesh_names",
]
