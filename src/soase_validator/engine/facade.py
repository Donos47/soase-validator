"""Engine facade: the only API that front ends call.

The :class:`Engine` combines settings resolution, the Layer chain, the
Reference Index, the parser, the validator, the completion helpers and the
manifest service. Front ends translate their own types to and from the model
types and call these methods; they hold no logic of their own.

State is cached per Project. A Project is identified by its settings: when a
setting that shapes the Chain changes (including the Game Version), the
Project's indexes are rebuilt from the Layer cache. Index maintenance after
a save or a file-watcher event is incremental and reports the open files
whose references the change can alter.

Unexpected exceptions never escape a Diagnostics-returning method. They are
logged to stderr through :mod:`logging`, and the Diagnostics collected so far
are returned together with ``SOASE-X001``. The module never writes to
stdout, because the LSP and MCP servers use it as their transport.

Disabled Diagnostic codes are removed in :meth:`Engine.validate_file` and
:meth:`Engine.manifest_check`, the two places that return Diagnostics to a
front end; :meth:`Engine.validate_directory` reuses the former.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from soase_validator.engine import completion, config
from soase_validator.engine import manifest_apply as manifest_writer
from soase_validator.engine.chain import Chain, Layer, resolve_chain
from soase_validator.engine.chainindex import (
    ChainIndex,
    Governor,
    build_chain_index,
    limited_checks_notice,
)
from soase_validator.engine.completion import AssistContext
from soase_validator.engine.config import EffectiveConfig, ResolvedSettings
from soase_validator.engine.deptracker import (
    DependencyTracker,
    IndexDelta,
    RecordingLookup,
    diff_layer_index,
)
from soase_validator.engine.diagnostics import (
    C040,
    CODE_CATALOGUE,
    M010,
    X001,
    filter_disabled,
)
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.manifests import (
    BackupRecord,
    ManifestData,
    ManifestEdit,
    ManifestRule,
    SyncPlan,
    governing_manifest,
    listed_name,
    manifest_check,
    plan_manifests,
    plan_sync,
    rule_for,
)
from soase_validator.engine.model import (
    CompletionItem,
    Diagnostic,
    FieldHelp,
    HoverResult,
    Location,
    Position,
    Range,
    Severity,
)
from soase_validator.engine.parser import parse, read_text_file
from soase_validator.engine.refindex import Entry, LayerIndex, RealFileSystem, RefKind, update_file
from soase_validator.engine.registry import LoadWarning, Registry, load_registry
from soase_validator.engine.validator import ValidationContext, definition_warnings, validate
from soase_validator.engine.versions import GameVersion

_LOG = logging.getLogger(__name__)

MANIFEST_EXTENSION = ".manifest"

#: Kinds whose names are limited to the files a governing manifest lists.
_GOVERNED_KINDS = {
    RefKind.ENTITY: "entity.manifest",
    RefKind.BRUSH: "brush.manifest",
}

_VCS_DIRECTORIES = frozenset({".git", ".svn", ".hg"})

Fingerprint = tuple[Any, ...]


@dataclass(slots=True)
class _ProjectState:
    """Cached state of one Project.

    Attributes:
        settings: Settings the state was built from.
        chain: The resolved Chain.
        chain_index: Merged lookup over the Chain; replaced as a whole when
            an index changes, so readers always see a consistent snapshot.
        tracker: References recorded per validated file.
        manifest_diagnostics: Result of the manifest check, or None when it
            must be computed again.
        manifest_by_file: The same Diagnostics grouped by file key.
    """

    settings: ResolvedSettings
    chain: Chain
    chain_index: ChainIndex
    tracker: DependencyTracker = field(default_factory=DependencyTracker)
    manifest_diagnostics: list[Diagnostic] | None = None
    manifest_by_file: dict[str, list[Diagnostic]] = field(default_factory=dict)


class Engine:
    """Single entry point used by the LSP, MCP, CLI and audit front ends."""

    def __init__(
        self,
        *,
        user_config_path: Path | None = None,
        env: Mapping[str, str] | None = None,
        layer_cache: LayerCache | None = None,
        registry: Registry | None = None,
    ) -> None:
        """Create an Engine.

        Args:
            user_config_path: User-level configuration file; defaults to the
                platform path.
            env: Environment to read; defaults to ``os.environ``.
            layer_cache: Layer index cache; defaults to a cache on the
                platform cache directory.
            registry: Definitions to use; the bundled Definitions are loaded
                on first use when omitted.
        """
        self._user_file = user_config_path
        self._env = env
        self._cache = LayerCache() if layer_cache is None else layer_cache
        self._fs = RealFileSystem()
        self._registry = registry
        self._lock = threading.RLock()
        self._states: dict[Fingerprint, _ProjectState] = {}
        self._editor_settings: Mapping[str, Any] = {}

    @property
    def registry(self) -> Registry:
        """The loaded Definitions, read from the bundled files on first use."""
        with self._lock:
            if self._registry is None:
                self._registry = load_registry()
            return self._registry

    def load_warnings(self) -> tuple[LoadWarning, ...]:
        """Report problems found while loading the Definitions.

        Returns:
            Load warnings of the Registry followed by the malformed
            ``constraint`` attributes (``SOASE-D001``).
        """
        registry = self.registry
        return (*registry.warnings, *definition_warnings(registry))

    def reload_configuration(self) -> None:
        """Forget every cached Project so the next call reads configuration again.

        Layer indexes stay in the Layer cache, so the rebuild only rescans
        the Layers.
        """
        with self._lock:
            self._states.clear()

    @property
    def user_config_file(self) -> Path:
        """The user-level configuration file, whether or not it exists."""
        return config.user_config_path() if self._user_file is None else self._user_file

    def set_editor_settings(self, settings: Mapping[str, Any] | None) -> None:
        """Set the editor-supplied settings used by every later call.

        The settings rank above the user-level file and below environment
        variables. Cached Projects are rebuilt on the next call when a
        setting that shapes a Chain changed.

        Args:
            settings: Settings using the ``soase.json`` key names; None or an
                empty mapping clears them.
        """
        self._editor_settings = dict(settings or {})

    def resolve_settings(
        self, path: Path, overrides: Mapping[str, Any] | None = None
    ) -> ResolvedSettings:
        """Resolve every setting for a file or directory.

        Args:
            path: The validated file or a directory.
            overrides: Editor-supplied settings using the ``soase.json`` key
                names; the settings from :meth:`set_editor_settings` apply
                when omitted.

        Returns:
            The resolved settings; invalid settings are listed in
            ``problems``.
        """
        editor = self._editor_settings if overrides is None else overrides
        return config.resolve_settings(path, editor, env=self._env, user_file=self._user_file)

    def effective_config(
        self, path: Path, overrides: Mapping[str, Any] | None = None
    ) -> EffectiveConfig:
        """Report the effective configuration with the source of each setting.

        Args:
            path: The validated file or a directory.
            overrides: Editor-supplied settings using the ``soase.json`` key
                names; the settings from :meth:`set_editor_settings` apply
                when omitted.

        Returns:
            The settings with provenance and Reference Root availability.
        """
        editor = self._editor_settings if overrides is None else overrides
        return config.effective_config(path, editor, env=self._env, user_file=self._user_file)

    def chain_layers(self, path: Path) -> tuple[Layer, ...]:
        """List the Layers of the Chain that governs a file or directory.

        Args:
            path: A file or directory.

        Returns:
            The Layers from lowest to highest; empty after an unexpected
            error.
        """
        try:
            return self._state_for(self.resolve_settings(path)).chain.layers
        except Exception:
            _LOG.exception("internal error while resolving the chain of %s", path)
            return ()

    def validate_file(
        self,
        path: Path,
        text: str | None = None,
        settings: ResolvedSettings | None = None,
    ) -> list[Diagnostic]:
        """Validate one file.

        Only files inside the Project's Mod Roots are validated; any other
        file gives no Diagnostics. A file whose extension has no Definition is
        not parsed, but still receives the manifest and override reports that
        concern it.

        Args:
            path: The file.
            text: The current text, for example an unsaved editor buffer;
                the file is read from disk when omitted.
            settings: Settings to use; resolved from ``path`` when omitted.

        Returns:
            Parser, validator, chain, override and manifest Diagnostics with
            disabled codes removed. After an unexpected error, the
            Diagnostics gathered so far plus ``SOASE-X001``.
        """
        found: list[Diagnostic] = []
        active = settings
        try:
            if active is None:
                active = self.resolve_settings(path)
            self._validate_into(path, text, active, found)
        except Exception as error:
            _LOG.exception("internal error while validating %s", path)
            found.append(_internal_error(path, error))
        disabled = active.disabled_codes if active is not None else frozenset()
        return filter_disabled(found, disabled)

    def validate_directory(self, root: Path) -> dict[Path, list[Diagnostic]]:
        """Validate every supported file below a directory.

        Settings are resolved for each directory, so a repository holding
        several overlay mods, each with its own ``soase.json``, validates
        every mod against its own Chain. The Project's own Layers are read
        from disk again first. Hidden and version-control directories are not
        entered.

        Args:
            root: The directory.

        Returns:
            Diagnostics per file, including files with none. Manifests are
            included, and so are files that only a manifest check reports.
        """
        base = _absolute(root)
        results: dict[Path, list[Diagnostic]] = {}
        try:
            self._walk_into(base, results)
        except Exception as error:
            _LOG.exception("internal error while validating %s", base)
            results.setdefault(base, []).append(_internal_error(base, error))
        return results

    def complete(self, path: Path, text: str, position: Position) -> list[CompletionItem]:
        """Compute completions at a position.

        Args:
            path: The edited file.
            text: Its current text.
            position: Zero-based cursor position.

        Returns:
            The candidates; empty after an unexpected error.
        """
        try:
            return completion.complete(text, position, self._assist(path))
        except Exception:
            _LOG.exception("internal error while completing in %s", path)
            return []

    def hover(self, path: Path, text: str, position: Position) -> HoverResult | None:
        """Compute hover content at a position.

        Args:
            path: The edited file.
            text: Its current text.
            position: Zero-based position.

        Returns:
            The content, or None when there is nothing to show or after an
            unexpected error.
        """
        try:
            return completion.hover(text, position, self._assist(path))
        except Exception:
            _LOG.exception("internal error while hovering in %s", path)
            return None

    def definition(self, path: Path, text: str, position: Position) -> Location | None:
        """Find the file that defines the reference under a position.

        Args:
            path: The edited file.
            text: Its current text.
            position: Zero-based position.

        Returns:
            The file of the highest Layer that provides the name, or None.
        """
        try:
            return completion.goto_definition(text, position, self._assist(path))
        except Exception:
            _LOG.exception("internal error while resolving a definition in %s", path)
            return None

    def field_help(self, structure: str, field_name: str, version: GameVersion) -> FieldHelp | None:
        """Look up the help of a field of a structure.

        Args:
            structure: Structure name.
            field_name: Field key.
            version: Game Version.

        Returns:
            The help, or None when the structure or the field is undefined.
        """
        return completion.field_help(self.registry, structure, field_name, version)

    def entity_types(self, version: GameVersion) -> list[str]:
        """List the ``entityType`` values valid for a Game Version.

        Args:
            version: Game Version.

        Returns:
            The values in declared order.
        """
        return completion.entity_types(self.registry, version)

    def on_file_saved(self, path: Path) -> set[Path]:
        """Update the Reference Index after a file changed on disk.

        Only the changed file is read again. The call covers a changed,
        added and deleted file.

        Args:
            path: The file.

        Returns:
            The other validated files whose references the change can alter;
            the caller validates them again. After a manifest changed, every
            validated file of the affected Projects.
        """
        target = _absolute(path)
        dependents: set[Path] = set()
        with self._lock:
            for state in self._states.values():
                dependents |= self._file_changed(state, target)
        dependents.discard(target)
        return dependents

    def on_layer_files_changed(self, layer: Layer) -> set[Path]:
        """Update the Reference Index after many files of a Layer changed.

        The Layer is scanned again and its index is replaced when the scan
        differs from the cached one.

        Args:
            layer: The Layer.

        Returns:
            The validated files whose references the changes can alter.
        """
        wanted = _key(layer.path)
        dependents: set[Path] = set()
        with self._lock:
            for state in self._states.values():
                dependents |= self._reindex(state, lambda other: _key(other.path) == wanted)
        return dependents

    def manifest_check(self, project: Path) -> list[Diagnostic]:
        """Check the manifests and files of a Project.

        Args:
            project: A directory or file of the Project.

        Returns:
            ``SOASE-M010`` to ``SOASE-M040`` Diagnostics with disabled codes
            removed; after an unexpected error, ``SOASE-X001``.
        """
        try:
            settings = self.resolve_settings(project)
            state = self._state_for(settings, refresh=True)
            return filter_disabled(self._manifest_diagnostics(state), settings.disabled_codes)
        except Exception as error:
            _LOG.exception("internal error while checking manifests of %s", project)
            return [_internal_error(project, error)]

    def manifest_plan(self, project: Path, *, remove_stale: bool = False) -> SyncPlan:
        """Plan the sync of the manifests of a Project.

        Args:
            project: A directory or file of the Project.
            remove_stale: Also plan the removal of entries that match no file.

        Returns:
            The plan; nothing is written.
        """
        settings = self.resolve_settings(project)
        state = self._state_for(settings, refresh=True)
        return plan_manifests(
            state.chain_index.indexes, settings.manifest, self._fs, remove_stale=remove_stale
        )

    def manifest_add_edit(self, file: Path) -> ManifestEdit | None:
        """Plan adding one unlisted file to the manifest that governs it.

        Args:
            file: A Project file reported by ``SOASE-M010``.

        Returns:
            The edit, or None when the file is not reported, the governing
            manifest lies outside the Project's own Layers, or the manifest
            cannot be read. Nothing is written.
        """
        try:
            settings = self.resolve_settings(file)
            state = self._state_for(settings)
            found = filter_disabled(self._manifest_diagnostics(state), settings.disabled_codes)
            target = _key(file)
            for diagnostic in found:
                if diagnostic.code != M010 or _key(diagnostic.file) != target:
                    continue
                data = diagnostic.data or {}
                manifest = Path(str(data.get("manifest", "")))
                name = data.get("name")
                rule = rule_for(manifest.name)
                owned = any(
                    layer.kind == "project" and _is_below(layer.path, manifest)
                    for layer in state.chain.layers
                )
                if not owned or rule is None or not isinstance(name, str):
                    return None
                text = self._fs.read_text(manifest)
                if text is None:
                    return None
                new_text = plan_sync(text, rule, [name])
                if new_text == text:
                    return None
                return ManifestEdit(manifest, text, new_text, (name,), ())
        except Exception:
            _LOG.exception("internal error while planning a manifest entry for %s", file)
        return None

    def manifest_apply(self, plan: SyncPlan) -> list[BackupRecord]:
        """Write the edits of a plan and refresh the Reference Index.

        Args:
            plan: A plan from :meth:`manifest_plan`.

        Returns:
            One backup record per written manifest.

        Raises:
            ValueError: If a manifest changed on disk since it was planned.
            OSError: If a backup or write fails.
        """
        records = manifest_writer.manifest_apply(plan)
        for record in records:
            self.on_file_saved(record.manifest_path)
        return records

    def _assist(self, path: Path) -> AssistContext:
        """Build the context of the completion helpers for a file.

        Args:
            path: The edited file.

        Returns:
            The context over the Project's merged lookup.
        """
        settings = self.resolve_settings(path)
        state = self._state_for(settings)
        return AssistContext(self.registry, settings.game_version, path, state.chain_index)

    def _validate_into(
        self, path: Path, text: str | None, settings: ResolvedSettings, out: list[Diagnostic]
    ) -> None:
        """Append every Diagnostic of one file to a list.

        The list grows stage by stage, so the caller keeps the earlier
        results when a later stage raises.

        Args:
            path: The file.
            text: The current text, or None to read the file.
            settings: Resolved settings.
            out: Receives the Diagnostics.

        Raises:
            OSError: If the file cannot be read.
        """
        if not _within(settings.mod_roots, path):
            return
        registry = self.registry
        state = self._state_for(settings)
        if registry.structure_for_extension(path.suffix) is not None:
            source = read_text_file(path) if text is None else text
            parsed = parse(source, path, settings.game_version)
            out.extend(parsed.diagnostics)
            lookup = RecordingLookup(state.chain_index)
            context = ValidationContext(
                registry, settings.game_version, path, settings.numeric, lookup
            )
            out.extend(validate(parsed, context))
            with self._lock:
                state.tracker.record(_absolute(path), lookup.references)
            out.extend(_chain_problems(state.chain, path))
            out.extend(
                limited_checks_notice(
                    state.chain, path, suppressed=settings.suppress_limited_notice
                )
            )
        if settings.report_overrides:
            out.extend(_override_notes(state.chain_index.indexes, path))
        self._manifest_diagnostics(state)
        out.extend(state.manifest_by_file.get(_key(path), ()))

    def _walk_into(self, base: Path, results: dict[Path, list[Diagnostic]]) -> None:
        """Validate the supported files below a directory.

        Args:
            base: Absolute directory.
            results: Receives the Diagnostics per file.
        """
        memo: dict[Path, ResolvedSettings] = {}
        refreshed: set[Fingerprint] = set()
        seen: list[tuple[_ProjectState, ResolvedSettings]] = []
        registry = self.registry
        for directory, subdirectories, names in os.walk(base):
            subdirectories[:] = sorted(d for d in subdirectories if not _skipped(d))
            folder = Path(directory)
            for name in sorted(names):
                file = folder / name
                suffix = file.suffix.casefold()
                if (
                    suffix != MANIFEST_EXTENSION
                    and registry.structure_for_extension(suffix) is None
                ):
                    continue
                if folder not in memo:
                    memo[folder] = self.resolve_settings(folder)
                settings = memo[folder]
                if not _within(settings.mod_roots, file):
                    continue
                fingerprint = _fingerprint(settings)
                state = self._state_for(settings, refresh=fingerprint not in refreshed)
                if fingerprint not in refreshed:
                    refreshed.add(fingerprint)
                    seen.append((state, settings))
                results[file] = self.validate_file(file, None, settings)
        reported = {_key(file) for file in results}
        for state, settings in seen:
            extra = filter_disabled(self._manifest_diagnostics(state), settings.disabled_codes)
            for diagnostic in extra:
                if _key(diagnostic.file) in reported or not _absolute(
                    diagnostic.file
                ).is_relative_to(base):
                    continue
                results.setdefault(_absolute(diagnostic.file), []).append(diagnostic)

    def _state_for(self, settings: ResolvedSettings, *, refresh: bool = False) -> _ProjectState:
        """Return the cached state of a Project, building it when needed.

        A Project whose settings changed (a different Game Version, Layers or
        Reference Root) is rebuilt and its old state is dropped.

        Args:
            settings: Resolved settings of the Project.
            refresh: Read the Project's own Layers from disk again.

        Returns:
            The state.
        """
        fingerprint = _fingerprint(settings)
        with self._lock:
            state = self._states.get(fingerprint)
            if state is None:
                for stale in [key for key in self._states if key[0] == fingerprint[0]]:
                    del self._states[stale]
                chain = resolve_chain(settings, self._env)
                index = build_chain_index(
                    chain, settings.game_version, self._cache, self._fs, language=settings.language
                )
                state = _ProjectState(settings, chain, index)
                state.chain_index = _with_governors(index, self._fs)
                self._states[fingerprint] = state
            elif refresh:
                self._reindex(state, lambda layer: layer.kind == "project")
            return state

    def _manifest_diagnostics(self, state: _ProjectState) -> list[Diagnostic]:
        """Return the manifest check of a Project, computing it when stale.

        Args:
            state: The Project state.

        Returns:
            The Diagnostics of all manifest types.
        """
        with self._lock:
            if state.manifest_diagnostics is None:
                found = manifest_check(state.chain_index.indexes, state.settings.manifest, self._fs)
                grouped: dict[str, list[Diagnostic]] = {}
                for diagnostic in found:
                    grouped.setdefault(_key(diagnostic.file), []).append(diagnostic)
                state.manifest_by_file = grouped
                state.manifest_diagnostics = found
            return state.manifest_diagnostics

    def _file_changed(self, state: _ProjectState, target: Path) -> set[Path]:
        """Apply one changed file to a Project's indexes.

        Args:
            state: The Project state.
            target: Absolute path of the changed file.

        Returns:
            The files to validate again.
        """
        indexes = list(state.chain_index.indexes)
        owners = [
            (len(index.layer.path.parts), position)
            for position, index in enumerate(indexes)
            if _is_below(index.layer.path, target)
        ]
        if not owners:
            return set()
        position = max(owners)[1]
        old = indexes[position]
        new = update_file(old, target, self._fs)
        if new is old:
            return set()
        self._cache.put(new, state.settings.game_version)
        indexes[position] = new
        if not target.exists():
            state.tracker.forget(target)
        return self._apply(
            state,
            indexes,
            [diff_layer_index(old, new)],
            manifest_touched=target.suffix.casefold() == MANIFEST_EXTENSION,
        )

    def _reindex(self, state: _ProjectState, wanted: Callable[[Layer], bool]) -> set[Path]:
        """Scan selected Layers again and apply the differences.

        Args:
            state: The Project state.
            wanted: Tells whether a Layer is scanned.

        Returns:
            The files to validate again.
        """
        indexes = list(state.chain_index.indexes)
        deltas: list[IndexDelta] = []
        manifest_touched = False
        for position, old in enumerate(indexes):
            if not wanted(old.layer):
                continue
            new = self._cache.get_or_build(
                old.layer, state.settings.game_version, self._fs, state.settings.language
            )
            if new.signature == old.signature:
                continue
            deltas.append(diff_layer_index(old, new))
            manifest_touched = manifest_touched or _manifest_changed(old, new)
            indexes[position] = new
        if not deltas:
            return set()
        return self._apply(state, indexes, deltas, manifest_touched=manifest_touched)

    def _apply(
        self,
        state: _ProjectState,
        indexes: Iterable[LayerIndex],
        deltas: list[IndexDelta],
        *,
        manifest_touched: bool,
    ) -> set[Path]:
        """Install new indexes in a Project and find the dependents.

        Args:
            state: The Project state.
            indexes: The Layer indexes after the change, lowest first.
            deltas: What changed per Layer.
            manifest_touched: Whether a manifest changed; the governed name
                sets then change for every reference.

        Returns:
            The files to validate again.
        """
        merged = replace(state.chain_index, indexes=tuple(indexes))
        state.chain_index = _with_governors(merged, self._fs)
        state.manifest_diagnostics = None
        found = set(state.tracker.dependents(deltas, state.chain.layers, state.settings.language))
        if manifest_touched:
            found |= state.tracker.tracked()
        return found


def _fingerprint(settings: ResolvedSettings) -> Fingerprint:
    """Identify the Project and Chain that settings describe.

    Args:
        settings: Resolved settings.

    Returns:
        A hashable key whose first item identifies the Project and whose
        second item holds everything that shapes its Chain and indexes.
    """
    anchor = (settings.project_file, settings.mod_roots)
    aliases = tuple(sorted((name, str(path)) for name, path in settings.aliases.items()))
    shape = (
        settings.game_version,
        settings.language,
        settings.layer_specs,
        aliases,
        settings.reference_roots.get(settings.game_version),
        settings.manifest,
    )
    return anchor, shape


def _with_governors(index: ChainIndex, fs: RealFileSystem) -> ChainIndex:
    """Limit the manifest-governed kinds of a merged lookup to listed files.

    Args:
        index: The merged lookup.
        fs: The file system.

    Returns:
        A lookup whose Entity and Brush names come only from files that the
        governing manifest lists. A kind without a governing manifest is not
        limited, so an overlay without manifests keeps working.
    """
    governors: dict[RefKind, Governor] = {}
    for kind, manifest in _GOVERNED_KINDS.items():
        rule = rule_for(manifest)
        if rule is None or rule.directory is None:
            continue
        governing = governing_manifest(index.indexes, rule, fs)
        if governing is None:
            continue
        governors[kind] = _listed_by(rule, governing.data)
    return replace(index, governors=governors)


def _listed_by(rule: ManifestRule, data: ManifestData) -> Governor:
    """Build the predicate that accepts the entries a manifest lists.

    Args:
        rule: The rule of the manifest type; it must state a directory.
        data: The parsed governing manifest.

    Returns:
        A predicate over index entries. An entry whose file is outside the
        governed directory is accepted, because the manifest does not name it.
    """
    directory = (rule.directory or "").casefold()

    def listed(entry: Entry) -> bool:
        if entry.file.parent.name.casefold() != directory:
            return True
        return data.lists(listed_name(rule, entry.file.name))

    return listed


def _manifest_changed(old: LayerIndex, new: LayerIndex) -> bool:
    """Tell whether any manifest file differs between two index versions.

    Args:
        old: The earlier index.
        new: The later index.

    Returns:
        True when a manifest was added, removed or modified.
    """
    return any(
        key.endswith(MANIFEST_EXTENSION) and old.stats.get(key) != new.stats.get(key)
        for key in old.stats.keys() | new.stats.keys()
    )


def _chain_problems(chain: Chain, file: Path) -> list[Diagnostic]:
    """Turn the problems of a Chain into Diagnostics on a file.

    Args:
        chain: The Chain.
        file: The validated file.

    Returns:
        One Diagnostic per cycle or missing Layer, at the start of the file.
    """
    start = Position(0, 0)
    found = []
    for problem in chain.problems:
        info = CODE_CATALOGUE.get(problem.code)
        severity = info.severity if info is not None else Severity.WARNING
        found.append(Diagnostic(file, Range(start, start), severity, problem.code, problem.message))
    return found


def _override_notes(indexes: tuple[LayerIndex, ...], file: Path) -> list[Diagnostic]:
    """Report a Project file that overrides a file of a lower Layer.

    Args:
        indexes: Layer indexes, lowest first.
        file: The file.

    Returns:
        One informational Diagnostic naming the highest lower Layer that
        holds a file at the same relative path; empty when the file is not
        in a Project Layer or overrides nothing.
    """
    target = _absolute(file)
    for position, index in enumerate(indexes):
        if index.layer.kind != "project" or not _is_below(index.layer.path, target):
            continue
        parts = target.relative_to(index.layer.path).parts
        key = "/".join(parts).casefold()
        if key not in index.files:
            continue
        for lower in reversed(indexes[:position]):
            if key in lower.files:
                message = (
                    f"{'/'.join(parts)} overrides the file of the same name in "
                    f"Layer {lower.layer.name}."
                )
                start = Position(0, 0)
                return [Diagnostic(file, Range(start, start), Severity.INFO, C040, message)]
        return []
    return []


def _internal_error(file: Path, error: Exception) -> Diagnostic:
    """Build the Diagnostic that marks results as partial.

    Args:
        file: The file or directory being processed.
        error: The exception that was caught.

    Returns:
        A ``SOASE-X001`` Diagnostic at the start of the file.
    """
    start = Position(0, 0)
    message = (
        f"Internal error ({type(error).__name__}); results may be partial. "
        "Details were written to the log."
    )
    return Diagnostic(file, Range(start, start), Severity.ERROR, X001, message)


def _absolute(path: Path) -> Path:
    """Make a path absolute and normalised without touching the disk.

    Args:
        path: The path.

    Returns:
        The absolute path.
    """
    return Path(os.path.abspath(path))


def _key(path: Path) -> str:
    """Build a string that is equal for paths naming the same file.

    Args:
        path: The path.

    Returns:
        The absolute path, case-normalised on case-insensitive systems.
    """
    return os.path.normcase(os.path.abspath(path))


def _is_below(root: Path, path: Path) -> bool:
    """Tell whether a path lies inside a directory.

    Args:
        root: The directory.
        path: The path.

    Returns:
        True when ``path`` is ``root`` or below it.
    """
    return _absolute(path).is_relative_to(_absolute(root))


def _within(roots: Iterable[Path], path: Path) -> bool:
    """Tell whether a path lies inside any of the directories.

    Args:
        roots: The directories.
        path: The path.

    Returns:
        True when some directory contains the path.
    """
    return any(_is_below(root, path) for root in roots)


def _skipped(name: str) -> bool:
    """Tell whether a directory is hidden or a version-control directory.

    Args:
        name: The directory name.

    Returns:
        True when the directory is not entered.
    """
    return name.startswith(".") or name.casefold() in _VCS_DIRECTORIES


__all__ = ["Engine"]
