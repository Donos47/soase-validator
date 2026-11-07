"""Merged reference lookup over a Chain.

A :class:`ChainIndex` holds the index of every usable Layer and answers
``resolve`` for the validator. The highest Layer that provides a name wins,
names are compared casefolded, and the next lower Layer that provides the
same name is reported as the one that is overridden.

Kinds that name files are answered from the Layers' file maps. Named kinds
are answered from the names the Layers define, and a built-in token from
:data:`BUILTIN_TOKENS`. A kind with none of these is never decided.

WHILE the Chain is incomplete, a name that no usable Layer provides may live
in a missing Layer, so it resolves to ``Unknown`` and the validator reports
nothing. A name that a usable Layer provides still resolves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from soase_validator.engine.chain import Chain, Layer
from soase_validator.engine.config import DEFAULT_LANGUAGE
from soase_validator.engine.diagnostics import C030
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.model import Diagnostic, Position, Range, Severity
from soase_validator.engine.nameindex import (
    NAMED_KINDS,
    BuiltinToken,
    builtin_token,
    requirement_met,
)
from soase_validator.engine.refindex import (
    FILE_REFERENCE_RULES,
    Entry,
    FileSystem,
    LayerIndex,
    RefKind,
    file_reference_keys,
)
from soase_validator.engine.validator import Found, NotFound, ResolveResult, Unknown
from soase_validator.engine.versions import GameVersion

Governor = Callable[[Entry], bool]
"""Tells whether the governing manifest of a kind lists an entry."""

CONFIGURATION_HINT = (
    "List the Layers in the 'layers' setting of soase.json, or set a Reference Root "
    "with 'soase-validator config set-reference-root'"
)


@dataclass(frozen=True, slots=True)
class Resolution:
    """The Layer that provides a name.

    Attributes:
        layer: The highest Layer that provides the name.
        entry: The name as that Layer defines it. For a file reference the
            entry names the file.
        overrides: The next lower Layer that provides the same name, or
            None when there is none.
    """

    layer: Layer
    entry: Entry
    overrides: Layer | None = None


@dataclass(frozen=True, slots=True)
class BuiltinResolution:
    """A name that needs no defining file.

    Attributes:
        token: The built-in token the name spells.
    """

    token: BuiltinToken


@dataclass(frozen=True, slots=True)
class ChainIndex:
    """Layer indexes of one Chain, searched from the highest Layer down.

    Attributes:
        indexes: Indexes of the usable Layers, lowest first.
        complete: Whether the Chain is complete; see :class:`Chain`.
        governors: Per kind, a predicate that accepts only the entries the
            governing manifest lists. A kind without a governor accepts
            every entry its Layers define.
        language: The configured language; selects the localized folders
            that file references try.
    """

    indexes: tuple[LayerIndex, ...]
    complete: bool = True
    governors: Mapping[RefKind, Governor] = field(default_factory=dict)
    language: str = DEFAULT_LANGUAGE

    def lookup(self, kind: str, name: str, file_extension: str = "") -> Resolution | None:
        """Find the Layer that provides a name.

        Args:
            kind: Reference kind, the validation type.
            name: The referenced name; comparison is case-insensitive.
            file_extension: Extension of the referencing file; selects
                whether a file name may carry its extension.

        Returns:
            The resolution, or None when no usable Layer provides the name,
            the kind is unknown, or the kind has no source rule.
        """
        try:
            ref_kind = RefKind(kind)
        except ValueError:
            return None
        hits = self._hits(ref_kind, name, file_extension)
        winner = next(hits, None)
        if winner is None:
            return None
        lower = next(hits, None)
        return Resolution(winner[0], winner[1], lower[0] if lower is not None else None)

    def resolve(self, kind: str, name: str, file_extension: str = "") -> ResolveResult:
        """Resolve a reference for the validator.

        Args:
            kind: Reference kind, the validation type.
            name: The referenced name; comparison is case-insensitive.
            file_extension: Extension of the referencing file.

        Returns:
            ``Found`` carrying the :class:`Resolution` when a usable Layer
            provides the name, or a :class:`BuiltinResolution` for a built-in
            token whose requirement is met. Otherwise ``NotFound`` for a
            complete Chain and a kind with a source rule, else ``Unknown``.
        """
        resolution = self.lookup(kind, name, file_extension)
        if resolution is not None:
            return Found(resolution)
        token = self._builtin(kind, name)
        if token is not None:
            return Found(BuiltinResolution(token))
        if self.complete and _has_source(kind):
            return NotFound()
        return Unknown()

    def _builtin(self, kind: str, name: str) -> BuiltinToken | None:
        """Find the built-in token a name spells, if its requirement is met.

        Args:
            kind: Reference kind, the validation type.
            name: The referenced name.

        Returns:
            The token, or None when the name is no token or the names the
            token requires are not defined in any usable Layer.
        """
        try:
            ref_kind = RefKind(kind)
        except ValueError:
            return None
        token = builtin_token(ref_kind, name)
        if token is None:
            return None
        defined = (key for index in self.indexes for key in index.names.get(ref_kind, {}))
        return token if requirement_met(token, defined) else None

    def _hits(self, kind: RefKind, name: str, file_extension: str) -> Iterator[tuple[Layer, Entry]]:
        """Yield the Layers that provide a name, highest first.

        Args:
            kind: The kind of name.
            name: The referenced name.
            file_extension: Extension of the referencing file.

        Returns:
            An iterator of ``(layer, entry)`` pairs.
        """
        keys = file_reference_keys(kind, name, file_extension, self.language)
        key = name.casefold()
        governor = self.governors.get(kind)
        for index in reversed(self.indexes):
            if keys is not None:
                path = next((index.files[k] for k in keys if k in index.files), None)
                if path is not None:
                    yield index.layer, Entry(name, kind, path, index.layer.name)
                continue
            entry = index.names.get(kind, {}).get(key)
            if entry is not None and (governor is None or governor(entry)):
                yield index.layer, entry


def _has_source(kind: str) -> bool:
    """Tell whether a kind has a rule that says where its names come from.

    Args:
        kind: The validation type.

    Returns:
        True for a file-reference kind and for a named kind with a source
        rule.
    """
    try:
        ref_kind = RefKind(kind)
    except ValueError:
        return False
    return ref_kind in FILE_REFERENCE_RULES or ref_kind in NAMED_KINDS


def build_chain_index(
    chain: Chain,
    version: GameVersion,
    cache: LayerCache | None = None,
    fs: FileSystem | None = None,
    governors: Mapping[RefKind, Governor] | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> ChainIndex:
    """Build the merged lookup for a Chain.

    Args:
        chain: The resolved Chain.
        version: The Project's Game Version.
        cache: Layer index cache; a new cache on the platform cache directory
            when omitted.
        fs: The file system; defaults to the real one.
        governors: Per-kind manifest predicates; see :class:`ChainIndex`.
        language: The configured language.

    Returns:
        The lookup over the Chain's usable Layers.
    """
    cache = LayerCache() if cache is None else cache
    indexes = tuple(
        cache.get_or_build(layer, version, fs, language)
        for layer in chain.layers
        if layer.status == "ok"
    )
    return ChainIndex(indexes, chain.complete, dict(governors or {}), language)


def unusable_layers(chain: Chain) -> Sequence[Layer]:
    """List the declared Layers that are missing or unusable.

    Args:
        chain: The Chain.

    Returns:
        Layers other than the Project whose status is not ``ok``, lowest
        first.
    """
    return [layer for layer in chain.layers if layer.kind != "project" and layer.status != "ok"]


def limited_checks_notice(
    chain: Chain, file: Path, *, suppressed: bool = False
) -> list[Diagnostic]:
    """Build the informational notice that reference checks are limited.

    Args:
        chain: The Chain the file is validated against.
        file: The validated file; the notice is stamped on it.
        suppressed: True when the notice is switched off by configuration.

    Returns:
        One ``SOASE-C030`` Diagnostic at the start of the file, naming each
        missing or unusable Layer and how to configure it; an empty list for
        a complete Chain or when suppressed.
    """
    if suppressed or chain.complete:
        return []
    problems = "; ".join(
        f"{layer.name} is {layer.status} ({layer.path})" for layer in unusable_layers(chain)
    )
    message = (
        f"Reference checks are limited because Layers are unavailable: {problems}. "
        f"Unresolved references are not reported. {CONFIGURATION_HINT}."
    )
    start = Position(0, 0)
    return [Diagnostic(file, Range(start, start), Severity.INFO, C030, message)]


__all__ = [
    "CONFIGURATION_HINT",
    "BuiltinResolution",
    "ChainIndex",
    "Governor",
    "Resolution",
    "build_chain_index",
    "limited_checks_notice",
    "unusable_layers",
]
