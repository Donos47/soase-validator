"""Dependency tracking between validated files and the Reference Index.

While a file is validated, a :class:`RecordingLookup` notes every reference
the validator resolves as a :class:`ResolvedRef`: the Layer that provided it
(None when nothing did), the kind and the casefolded name. Outcomes that did
not resolve (``NotFound`` and ``Unknown``) are recorded too, because such a
reference must be validated again when the name later appears.

A :class:`DependencyTracker` maps each validated file to its recorded set.
:func:`diff_layer_index` turns two versions of a Layer index into an
:class:`IndexDelta` (names and file keys that appeared or disappeared), and
:func:`affected_files` selects the tracked files that must be validated again.

Override semantics: a reference that resolved in Layer W is decided by the
highest Layer that provides the name.
A change to the name in Layer L can alter that outcome only when L is W or
above it in the Chain. A change in a Layer below W is overridden by W and
yields no dependent. A reference that did not resolve has no providing Layer,
so a change in any Layer of the Chain yields it as a dependent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from soase_validator.engine.chain import Layer
from soase_validator.engine.chainindex import Resolution
from soase_validator.engine.config import DEFAULT_LANGUAGE
from soase_validator.engine.nameindex import builtin_token, requirement_met
from soase_validator.engine.refindex import LayerIndex, RefKind, file_reference_keys
from soase_validator.engine.validator import Found, ReferenceLookup, ResolveResult


@dataclass(frozen=True, slots=True)
class ResolvedRef:
    """One reference a validated file resolved.

    Attributes:
        layer: The Layer that provided the name, or None when the reference
            did not resolve or the provider is not known.
        kind: The kind of name.
        name: The referenced name, casefolded.
        file_extension: Casefolded extension of the referencing file; it
            selects the candidate file names of a file-reference kind.
    """

    layer: Layer | None
    kind: RefKind
    name: str
    file_extension: str = ""


@dataclass(frozen=True, slots=True)
class IndexDelta:
    """What changed in one Layer index.

    Attributes:
        layer: The changed Layer.
        names: ``(kind, casefolded name)`` pairs that were added or removed.
        files: Casefolded relative paths that were added or removed.
    """

    layer: Layer
    names: frozenset[tuple[RefKind, str]] = frozenset()
    files: frozenset[str] = frozenset()

    @property
    def empty(self) -> bool:
        """Tell whether nothing changed.

        Returns:
            True when no name and no file key changed.
        """
        return not self.names and not self.files


class RecordingLookup:
    """A :class:`ReferenceLookup` that records what it resolves.

    Attributes:
        references: The references resolved so far.
    """

    def __init__(self, inner: ReferenceLookup) -> None:
        """Wrap a lookup.

        Args:
            inner: The lookup that answers.
        """
        self._inner = inner
        self._seen: set[ResolvedRef] = set()

    @property
    def references(self) -> frozenset[ResolvedRef]:
        """Return the recorded references.

        Returns:
            An immutable snapshot.
        """
        return frozenset(self._seen)

    def resolve(self, kind: str, name: str, file_extension: str = "") -> ResolveResult:
        """Resolve a reference and record it.

        Args:
            kind: Reference kind, the validation type. A kind that is not a
                Reference Index kind is answered but not recorded.
            name: The referenced name.
            file_extension: Extension of the referencing file.

        Returns:
            The result of the wrapped lookup, unchanged.
        """
        result = self._inner.resolve(kind, name, file_extension)
        try:
            ref_kind = RefKind(kind)
        except ValueError:
            return result
        layer = None
        if isinstance(result, Found) and isinstance(result.detail, Resolution):
            layer = result.detail.layer
        self._seen.add(ResolvedRef(layer, ref_kind, name.casefold(), file_extension.casefold()))
        return result


class DependencyTracker:
    """Maps validated files to the references they resolved."""

    def __init__(self) -> None:
        """Create an empty tracker."""
        self._refs: dict[Path, frozenset[ResolvedRef]] = {}

    def record(self, file: Path, references: Iterable[ResolvedRef]) -> None:
        """Replace the recorded references of a file.

        Args:
            file: The validated file.
            references: Everything the last validation resolved.
        """
        self._refs[file] = frozenset(references)

    def forget(self, file: Path) -> None:
        """Drop a file, for example when it is closed or deleted.

        Args:
            file: The file.
        """
        self._refs.pop(file, None)

    def references_of(self, file: Path) -> frozenset[ResolvedRef]:
        """Return the references recorded for a file.

        Args:
            file: The file.

        Returns:
            The set; empty for an untracked file.
        """
        return self._refs.get(file, frozenset())

    def tracked(self) -> frozenset[Path]:
        """Return the tracked files.

        Returns:
            The files with a recorded set.
        """
        return frozenset(self._refs)

    def dependents(
        self,
        deltas: Iterable[IndexDelta],
        layers: Sequence[Layer],
        language: str = DEFAULT_LANGUAGE,
    ) -> frozenset[Path]:
        """Find the tracked files that changes to Layer indexes affect.

        Args:
            deltas: Changes per Layer.
            layers: The Layers of the Chain, lowest first.
            language: The configured language.

        Returns:
            Files that recorded a reference the changes can alter.
        """
        return affected_files(self._refs, deltas, layers, language)


def diff_layer_index(old: LayerIndex | None, new: LayerIndex) -> IndexDelta:
    """Compare two versions of one Layer's index.

    Args:
        old: The earlier index, or None when the Layer is new.
        new: The later index.

    Returns:
        The names and file keys present in only one of them.
    """
    old_names = _name_pairs(old)
    new_names = _name_pairs(new)
    old_files = frozenset(old.files) if old is not None else frozenset()
    return IndexDelta(
        new.layer,
        old_names ^ new_names,
        old_files ^ frozenset(new.files),
    )


def _name_pairs(index: LayerIndex | None) -> frozenset[tuple[RefKind, str]]:
    """List the ``(kind, casefolded name)`` pairs an index defines.

    Args:
        index: The index, or None.

    Returns:
        The pairs; empty for None.
    """
    if index is None:
        return frozenset()
    return frozenset((kind, name) for kind, entries in index.names.items() for name in entries)


def affected_files(
    tracked: Mapping[Path, frozenset[ResolvedRef]],
    deltas: Iterable[IndexDelta],
    layers: Sequence[Layer],
    language: str = DEFAULT_LANGUAGE,
) -> frozenset[Path]:
    """Select the files whose recorded references the deltas can alter.

    Args:
        tracked: Recorded references per file.
        deltas: Changes per Layer.
        layers: The Layers of the Chain, lowest first. A delta for a Layer
            outside the Chain is ignored.
        language: The configured language.

    Returns:
        The files to validate again. A reference whose recorded provider is
        no longer in the Chain is always affected.
    """
    rank = {layer: position for position, layer in enumerate(layers)}
    live = [delta for delta in deltas if not delta.empty and delta.layer in rank]
    if not live:
        return frozenset()
    result: set[Path] = set()
    for file, references in tracked.items():
        if any(_alters(ref, delta, rank, language) for ref in references for delta in live):
            result.add(file)
    return frozenset(result)


def _alters(ref: ResolvedRef, delta: IndexDelta, rank: Mapping[Layer, int], language: str) -> bool:
    """Tell whether a change can alter how one reference resolves.

    Args:
        ref: The recorded reference.
        delta: A change in one Layer.
        rank: Position of each Layer in the Chain, lowest first.
        language: The configured language.

    Returns:
        True when the changed Layer is the provider or above it, or the
        reference had no provider, and the delta touches the referenced
        name or one of its candidate files.
    """
    if ref.layer is not None and ref.layer in rank and rank[delta.layer] < rank[ref.layer]:
        return False
    keys = file_reference_keys(ref.kind, ref.name, ref.file_extension, language)
    if keys is not None:
        return any(key in delta.files for key in keys)
    token = builtin_token(ref.kind, ref.name)
    if token is not None and token.requires is not None:
        return any(
            kind is ref.kind and requirement_met(token, (name,)) for kind, name in delta.names
        )
    return (ref.kind, ref.name) in delta.names


__all__ = [
    "DependencyTracker",
    "IndexDelta",
    "RecordingLookup",
    "ResolvedRef",
    "affected_files",
    "diff_layer_index",
]
