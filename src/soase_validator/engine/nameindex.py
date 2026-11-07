"""Names defined by the files of one Layer.

Each indexed kind has source rules in :data:`NAME_SOURCES`: the extension and
directory of the defining files, the key path of the blocks that define a name
and the key inside a block that holds it. A localized rule reads the files
of the configured language, then of the fallback language, then of the
directory at the Layer root. Entity names are the stems of the files that
:data:`ENTITY_EXTENSION` and :data:`ENTITY_DIRECTORY` select.
:data:`FILE_LOCAL_NAME_SOURCES` lists names that only the file declaring them
can reference; they are never indexed. :data:`BUILTIN_TOKENS` lists names that
need no defining file. :data:`SCOPED_TOKENS` lists names that need none only in
one referencing context.

A file that matches several source rules is parsed once and defines the names
of every matching rule. When several files define one name, the file earliest
in lookup order provides it: localized files by language order, then by
casefolded path.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from soase_validator.engine.config import DEFAULT_LANGUAGE
from soase_validator.engine.parser import Node, StringValue, parse
from soase_validator.engine.refindex import (
    Entry,
    FileSystem,
    LayerIndex,
    RealFileSystem,
    RefKind,
    localized_prefixes,
)


@dataclass(frozen=True, slots=True)
class NameSource:
    """Where the names of one kind are defined.

    Attributes:
        kind: The kind of name.
        extension: Casefolded extension of the defining files, with the dot.
        directory: Casefolded game data directory directly holding the
            defining files, or None when the files may be anywhere in the
            indexed scope.
        blocks: Block keys that define a name.
        name_key: Key inside a block that holds the name.
        parents: Keys of the containers from the file root down to the
            blocks; empty when the blocks are top-level.
        localized: True when the files may also sit in ``directory`` below
            the configured and the fallback language folders.
    """

    kind: RefKind
    extension: str
    directory: str | None
    blocks: tuple[str, ...]
    name_key: str
    parents: tuple[str, ...] = ()
    localized: bool = False


ENTITY_DIRECTORY = "gameinfo"
ENTITY_EXTENSION = ".entity"

NAME_SOURCES: tuple[NameSource, ...] = (
    NameSource(RefKind.BRUSH, ".brushes", None, ("brush",), "name"),
    NameSource(RefKind.STRING_INFO, ".str", "string", ("StringInfo",), "ID", localized=True),
    NameSource(RefKind.SOUND, ".sounddata", "gameinfo", ("effect", "music"), "name"),
    NameSource(
        RefKind.EXPLOSION, ".explosiondata", "gameinfo", ("explosionEffectGroup",), "groupName"
    ),
    NameSource(
        RefKind.ORBIT_BODY_TYPE, ".galaxyscenariodef", "gameinfo", ("orbitBodyType",), "typeName"
    ),
    NameSource(
        RefKind.GALAXY_DESIGN,
        ".galaxyscenariodef",
        "gameinfo",
        ("starType", "planetType", "planetItemType", "playerType", "player"),
        "designName",
    ),
    NameSource(
        RefKind.GALAXY_DESIGN,
        ".constants",
        "gameinfo",
        ("minorFactionPlayerDef",),
        "name",
        parents=("GameplayConstants", "minorFactionsData"),
    ),
    NameSource(
        RefKind.GALAXY_TEMPLATE,
        ".galaxyscenariodef",
        "gameinfo",
        ("planetItemsTemplate",),
        "templateName",
    ),
)

#: Per kind and referencing file extension, the dotted key paths (from the
#: file root) whose quoted values the file itself declares. A reference in
#: that file that equals one of them resolves without a lookup.
FILE_LOCAL_NAME_SOURCES: Mapping[RefKind, Mapping[str, tuple[str, ...]]] = {
    RefKind.GALAXY_DESIGN: {".galaxy": ("player.designName",)},
    RefKind.GALAXY_TEMPLATE: {".galaxy": ("template.templateName",)},
}


@dataclass(frozen=True, slots=True)
class BuiltinToken:
    """A name that needs no defining file.

    Attributes:
        kind: The kind of name.
        name: The token as written.
        requires: Full-match pattern over the casefolded names of the same
            kind, or None. The token is valid only while at least one such
            name is defined in the Chain.
    """

    kind: RefKind
    name: str
    requires: str | None = None


BUILTIN_TOKENS: tuple[BuiltinToken, ...] = (
    BuiltinToken(RefKind.GALAXY_DESIGN, "NoOwner"),
    BuiltinToken(RefKind.GALAXY_DESIGN, "PlanetOwner"),
    BuiltinToken(RefKind.GALAXY_DESIGN, "RandomMilitia", "militia[0-9]+"),
)


@dataclass(frozen=True, slots=True)
class ScopedToken:
    """A name that needs no defining file in one referencing context only.

    Attributes:
        kind: The kind of name.
        name: The token as written; comparison is case-insensitive.
        extension: Casefolded extension of the referencing file.
        path: Trailing key path of the referencing node.
        sibling_key: Key of a sibling node of the referencing node.
        sibling_value: Exact quoted value that sibling must hold.
    """

    kind: RefKind
    name: str
    extension: str
    path: tuple[str, ...]
    sibling_key: str
    sibling_value: str


SCOPED_TOKENS: tuple[ScopedToken, ...] = tuple(
    ScopedToken(
        RefKind.GALAXY_DESIGN,
        race,
        ".galaxy",
        ("condition", "param"),
        "type",
        "PlanetOwnerIsRaceQuickStart",
    )
    for race in ("Tech", "Psi", "Phase")
)

#: Kinds that :func:`index_names` fills in.
NAMED_KINDS = frozenset({RefKind.ENTITY, *(source.kind for source in NAME_SOURCES)})


def _directly_in(key: str, directory: str | None) -> bool:
    """Tell whether a relative path is a file directly in a directory.

    Args:
        key: Casefolded ``/``-separated relative path.
        directory: Casefolded directory name, or None for any location.

    Returns:
        True when ``directory`` is None or the file sits directly in it.
    """
    if directory is None:
        return True
    parts = key.split("/")
    return len(parts) == 2 and parts[0] == directory


def _source_applies(source: NameSource, key: str, language: str) -> bool:
    """Tell whether a file can define names under a source rule.

    Args:
        source: The rule.
        key: Casefolded ``/``-separated path of the file below the Layer root.
        language: The configured language.

    Returns:
        True when the extension matches and the file sits in the rule's
        directory, or in its localized folders for the two languages in use.
    """
    if PurePosixPath(key).suffix != source.extension:
        return False
    if _directly_in(key, source.directory):
        return True
    if not source.localized or source.directory is None:
        return False
    return any(
        key.startswith(prefix) and "/" not in key[len(prefix) :]
        for prefix in localized_prefixes(source.directory, language)
    )


def _lookup_order(key: str, language: str) -> tuple[int, str]:
    """Sort key that puts files earlier in lookup order first.

    Args:
        key: Casefolded ``/``-separated path of the file below the Layer root.
        language: The configured language.

    Returns:
        The position of the localized folder holding the file (the configured
        language, the fallback language, the Layer root), then the path. A
        file of no localized rule gets position 0.
    """
    for source in NAME_SOURCES:
        if source.localized and source.directory is not None:
            for position, prefix in enumerate(localized_prefixes(source.directory, language)):
                if key.startswith(prefix):
                    return position, key
    return 0, key


def _containers(nodes: list[Node], parents: tuple[str, ...]) -> list[Node]:
    """Descend a key path from the file root.

    Args:
        nodes: Top-level nodes of the parsed file.
        parents: Keys of the containers, outermost first.

    Returns:
        The nodes below the last container; the top-level nodes for an empty
        path.
    """
    level = nodes
    for key in parents:
        level = [child for node in level if node.key == key for child in node.children]
    return level


def _block_names(nodes: list[Node], source: NameSource) -> list[str]:
    """Read the names a file defines for one source rule.

    Args:
        nodes: Top-level nodes of the parsed file.
        source: The rule.

    Returns:
        The names in file order. A block without a quoted name is skipped.
    """
    names: list[str] = []
    for node in _containers(nodes, source.parents):
        if node.key not in source.blocks or node.value is not None:
            continue
        for child in node.children:
            if child.key == source.name_key and isinstance(child.value, StringValue):
                if child.value.text:
                    names.append(child.value.text)
                break
    return names


def _add(
    names: dict[RefKind, dict[str, Entry]], kind: RefKind, name: str, file: Path, layer: str
) -> None:
    """Record a name unless an earlier file already defines it.

    Args:
        names: The collection being built.
        kind: The kind of name.
        name: The name in its original casing.
        file: The defining file.
        layer: The Layer name.
    """
    names.setdefault(kind, {}).setdefault(name.casefold(), Entry(name, kind, file, layer))


def defined_names(
    key: str,
    path: Path,
    fs: FileSystem,
    kinds: frozenset[RefKind] | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> list[tuple[RefKind, str]]:
    """List the names one file defines.

    Args:
        key: Casefolded ``/``-separated path of the file below the Layer root.
        path: The file path.
        fs: The file system. A file that cannot be read defines nothing.
        kinds: Only these kinds are read, or None for every kind.
        language: The configured language; a localized rule reads only the
            files of this language and the fallback language.

    Returns:
        ``(kind, name)`` pairs, grouped by source rule and in file order
        within each, with the name in its original casing.
    """
    extension = PurePosixPath(key).suffix
    if extension == ENTITY_EXTENSION and _directly_in(key, ENTITY_DIRECTORY):
        if kinds is not None and RefKind.ENTITY not in kinds:
            return []
        return [(RefKind.ENTITY, path.stem)]
    matching = [
        source
        for source in NAME_SOURCES
        if _source_applies(source, key, language) and (kinds is None or source.kind in kinds)
    ]
    if not matching:
        return []
    text = fs.read_text(path)
    if text is None:
        return []
    nodes = parse(text, path).nodes
    return [(source.kind, name) for source in matching for name in _block_names(nodes, source)]


def index_names(
    index: LayerIndex, fs: FileSystem | None = None, language: str | None = None
) -> LayerIndex:
    """Fill in the names that the files of a Layer define.

    Files are visited in lookup order, so the first file in that order wins
    when two files define the same name.

    Args:
        index: The Layer index; its existing names are replaced.
        fs: The file system; defaults to the real one. A file that cannot be
            read defines nothing.
        language: The configured language; defaults to the index's own.

    Returns:
        A new index with ``names`` and ``language`` set.
    """
    fs = RealFileSystem() if fs is None else fs
    language = index.language if language is None else language
    layer = index.layer
    names: dict[RefKind, dict[str, Entry]] = {}
    for key in sorted(index.files, key=lambda k: _lookup_order(k, language)):
        path = index.files[key]
        for kind, name in defined_names(key, path, fs, language=language):
            _add(names, kind, name, path, layer.name)
    frozen: Mapping[RefKind, Mapping[str, Entry]] = names
    return replace(index, names=frozen, language=language)


def update_names(
    index: LayerIndex,
    key: str,
    previous: Path | None,
    fs: FileSystem | None = None,
) -> LayerIndex:
    """Bring the names up to date after one file changed.

    The result equals :func:`index_names` on the same files. Names the file
    defined or defines now are decided again over all defining files of the
    same kinds, so a name another file also defines falls back to the first
    file in casefolded path order.

    Args:
        index: The index whose ``files`` already reflect the change.
        key: Casefolded relative path of the changed file.
        previous: The path the file had in the index before the change, or
            None when it was not indexed.
        fs: The file system; defaults to the real one.

    Returns:
        A new index, or ``index`` itself when the file defines no names now
        and defined none before.
    """
    fs = RealFileSystem() if fs is None else fs
    path = index.files.get(key)
    language = index.language
    current = defined_names(key, path, fs, language=language) if path is not None else []
    stale = {path_ for path_ in (previous, path) if path_ is not None}
    touched = {(kind, name.casefold()) for kind, name in current}
    for kind, entries in index.names.items():
        touched.update((kind, name) for name, entry in entries.items() if entry.file in stale)
    if not touched:
        return index
    kinds = frozenset(kind for kind, _ in touched)
    winners: dict[tuple[RefKind, str], Entry] = {}
    for other_key in sorted(index.files, key=lambda k: _lookup_order(k, language)):
        other = index.files[other_key]
        found = (
            current if other_key == key else defined_names(other_key, other, fs, kinds, language)
        )
        for kind, name in found:
            slot = (kind, name.casefold())
            if slot in touched:
                winners.setdefault(slot, Entry(name, kind, other, index.layer.name))
    names: dict[RefKind, dict[str, Entry]] = {k: dict(v) for k, v in index.names.items()}
    for kind, name in touched:
        names.get(kind, {}).pop(name, None)
    for (kind, name), entry in winners.items():
        names.setdefault(kind, {})[name] = entry
    frozen: Mapping[RefKind, Mapping[str, Entry]] = {k: v for k, v in names.items() if v}
    return replace(index, names=frozen)


def builtin_token(kind: RefKind, name: str) -> BuiltinToken | None:
    """Find the built-in token a name spells.

    Args:
        kind: The kind of name.
        name: The referenced name; comparison is case-insensitive.

    Returns:
        The token, or None.
    """
    wanted = name.casefold()
    return next((t for t in BUILTIN_TOKENS if t.kind is kind and t.name.casefold() == wanted), None)


def scoped_token(
    kind: RefKind,
    name: str,
    extension: str,
    path: tuple[str, ...],
    siblings: Mapping[str, str],
) -> ScopedToken | None:
    """Find the scoped token a name spells in a referencing context.

    Args:
        kind: The kind of name.
        name: The referenced name; comparison is case-insensitive.
        extension: Casefolded extension of the referencing file.
        path: Key path of the referencing node from the file root.
        siblings: Quoted values of the node's siblings by key.

    Returns:
        The token, or None when the name is no token or the context differs.
    """
    wanted = name.casefold()
    return next(
        (
            t
            for t in SCOPED_TOKENS
            if t.kind is kind
            and t.name.casefold() == wanted
            and t.extension == extension
            and path[-len(t.path) :] == t.path
            and siblings.get(t.sibling_key) == t.sibling_value
        ),
        None,
    )


def requirement_met(token: BuiltinToken, names: Iterable[str]) -> bool:
    """Tell whether a token's required name is defined.

    Args:
        token: The token.
        names: Casefolded names of the token's kind.

    Returns:
        True when the token has no requirement or a name matches it.
    """
    if token.requires is None:
        return True
    pattern = re.compile(token.requires)
    return any(pattern.fullmatch(name) for name in names)


__all__ = [
    "BUILTIN_TOKENS",
    "ENTITY_DIRECTORY",
    "ENTITY_EXTENSION",
    "FILE_LOCAL_NAME_SOURCES",
    "NAMED_KINDS",
    "NAME_SOURCES",
    "SCOPED_TOKENS",
    "BuiltinToken",
    "NameSource",
    "ScopedToken",
    "builtin_token",
    "defined_names",
    "index_names",
    "requirement_met",
    "scoped_token",
    "update_names",
]
