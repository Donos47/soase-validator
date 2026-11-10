"""LSP server for soase-validator.

The server translates between LSP types and Engine model types and calls the
Engine facade; it holds no validation logic. Engine calls run in a worker
thread so the event loop stays responsive. stdout carries the protocol, so
logging goes to stderr only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from soase_validator.engine.config import PROJECT_FILE_NAME
from soase_validator.engine.diagnostics import M010
from soase_validator.engine.facade import Engine
from soase_validator.engine.manifests import ManifestEdit
from soase_validator.engine.model import (
    CompletionItem,
    Diagnostic,
    HoverResult,
    Location,
    Position,
    Range,
    Severity,
)

SERVER_NAME = "soase-validator"
SERVER_VERSION = "0.1.1"
SETTINGS_SECTION = "soase-validator"
WATCH_REGISTRATION_ID = "soase-validator-file-watchers"

_LOG = logging.getLogger(__name__)

_SEVERITIES = {
    Severity.ERROR: types.DiagnosticSeverity.Error,
    Severity.WARNING: types.DiagnosticSeverity.Warning,
    Severity.INFO: types.DiagnosticSeverity.Information,
}

_COMPLETION_KINDS = {
    "key": types.CompletionItemKind.Property,
    "enum": types.CompletionItemKind.EnumMember,
    "reference": types.CompletionItemKind.Reference,
    "entity_type": types.CompletionItemKind.Value,
}


def to_lsp_range(value: Range) -> types.Range:
    """Convert an Engine range to an LSP range.

    Args:
        value: Zero-based Engine range.

    Returns:
        The LSP range; both sides are zero-based.
    """
    return types.Range(
        start=types.Position(line=value.start.line, character=value.start.col),
        end=types.Position(line=value.end.line, character=value.end.col),
    )


def to_lsp_diagnostic(diagnostic: Diagnostic) -> types.Diagnostic:
    """Convert an Engine Diagnostic to an LSP Diagnostic.

    Args:
        diagnostic: The Engine Diagnostic.

    Returns:
        The LSP Diagnostic; info severity maps to Information.
    """
    return types.Diagnostic(
        range=to_lsp_range(diagnostic.range),
        message=diagnostic.message,
        severity=_SEVERITIES[diagnostic.severity],
        code=diagnostic.code,
        source=SERVER_NAME,
        data=dict(diagnostic.data) if diagnostic.data is not None else None,
    )


def to_lsp_completion(item: CompletionItem) -> types.CompletionItem:
    """Convert an Engine completion candidate to an LSP completion item.

    Args:
        item: The Engine candidate.

    Returns:
        The LSP completion item.
    """
    return types.CompletionItem(
        label=item.label,
        kind=_COMPLETION_KINDS.get(item.kind),
        detail=item.detail,
        documentation=(
            types.MarkupContent(kind=types.MarkupKind.Markdown, value=item.documentation)
            if item.documentation
            else None
        ),
    )


def to_lsp_hover(result: HoverResult) -> types.Hover:
    """Convert an Engine hover result to an LSP hover.

    Args:
        result: The Engine hover result.

    Returns:
        The LSP hover with Markdown contents.
    """
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=result.contents),
        range=to_lsp_range(result.range) if result.range is not None else None,
    )


def to_lsp_location(location: Location) -> types.Location:
    """Convert an Engine location to an LSP location.

    Args:
        location: The Engine location.

    Returns:
        The LSP location with a ``file`` URI.
    """
    return types.Location(uri=from_fs_path(str(location.file)), range=to_lsp_range(location.range))


def editor_settings_from(payload: Any) -> dict[str, Any]:
    """Extract the settings mapping from an editor payload.

    Args:
        payload: The initialization options or the ``settings`` member of a
            configuration-change notification.

    Returns:
        The settings using the ``soase.json`` key names. When the payload
        holds a ``soase-validator`` section, only that section is used.
        Anything that is not a mapping gives an empty mapping.
    """
    if not isinstance(payload, Mapping):
        return {}
    section = payload.get(SETTINGS_SECTION)
    if isinstance(section, Mapping):
        return dict(section)
    return dict(payload)


def text_end_position(text: str) -> types.Position:
    """Compute the position just after the last character of a text.

    Args:
        text: Document text with LF, CRLF or CR line ends.

    Returns:
        The zero-based position, counting the character offset in UTF-16
        code units as the protocol default requires.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    last = lines[-1]
    return types.Position(line=len(lines) - 1, character=len(last.encode("utf-16-le")) // 2)


def to_lsp_workspace_edit(edit: ManifestEdit) -> types.WorkspaceEdit:
    """Convert a manifest edit to a workspace edit.

    Args:
        edit: The planned edit.

    Returns:
        An edit replacing the whole manifest text.
    """
    whole = types.Range(
        start=types.Position(line=0, character=0), end=text_end_position(edit.original_text)
    )
    return types.WorkspaceEdit(
        changes={
            from_fs_path(str(edit.manifest_path)): [
                types.TextEdit(range=whole, new_text=edit.new_text)
            ]
        }
    )


def watch_patterns(
    roots: Iterable[Path], user_file: Path, *, relative_patterns: bool
) -> list[types.FileSystemWatcher]:
    """Build the file watchers for Layers, ``soase.json`` and the user file.

    Args:
        roots: Layer directories, each watched recursively.
        user_file: The user-level configuration file.
        relative_patterns: Whether the client supports relative patterns,
            which can name directories outside the workspace.

    Returns:
        The watchers, without duplicates.
    """
    watchers: list[types.FileSystemWatcher] = [
        types.FileSystemWatcher(glob_pattern=f"**/{PROJECT_FILE_NAME}")
    ]
    seen: set[str] = set()

    def add(base: Path, pattern: str) -> None:
        key = os.path.normcase(os.path.join(str(base), pattern))
        if key in seen:
            return
        seen.add(key)
        if relative_patterns:
            glob: types.GlobPattern = types.RelativePattern(
                base_uri=from_fs_path(str(base)) or "", pattern=pattern
            )
        else:
            glob = f"{base.as_posix()}/{pattern}"
        watchers.append(types.FileSystemWatcher(glob_pattern=glob))

    for root in roots:
        add(root, "**/*")
    add(user_file.parent, user_file.name)
    return watchers


def is_configuration_file(path: Path, user_file: Path) -> bool:
    """Tell whether a changed file is a configuration file.

    Args:
        path: The changed file.
        user_file: The user-level configuration file.

    Returns:
        True for any ``soase.json`` and for the user-level file.
    """
    if path.name.casefold() == PROJECT_FILE_NAME:
        return True
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(user_file))


def select_open(uris: Iterable[str], paths: Iterable[Path]) -> list[str]:
    """Pick the document URIs that name one of the given files.

    Args:
        uris: URIs of the open documents.
        paths: Files to match.

    Returns:
        The matching URIs in input order. URIs that are not file URIs are
        skipped.
    """
    wanted = {os.path.normcase(os.path.abspath(path)) for path in paths}
    selected = []
    for uri in uris:
        try:
            path = _path_of(uri)
        except ValueError:
            continue
        if os.path.normcase(os.path.abspath(path)) in wanted:
            selected.append(uri)
    return selected


def _path_of(uri: str) -> Path:
    """Convert a document URI to a file system path.

    Args:
        uri: A ``file`` URI.

    Returns:
        The path.

    Raises:
        ValueError: If the URI is not a file URI.
    """
    path = to_fs_path(uri)
    if path is None:
        raise ValueError(f"not a file URI: {uri}")
    return Path(path)


def create_server(engine: Engine | None = None) -> LanguageServer:
    """Build the language server and register its handlers.

    Args:
        engine: Engine to use; a new one is created when omitted.

    Returns:
        The configured server, not yet started.
    """
    backend = Engine() if engine is None else engine
    server = LanguageServer(
        SERVER_NAME, SERVER_VERSION, text_document_sync_kind=types.TextDocumentSyncKind.Full
    )

    def publish(uri: str, diagnostics: list[types.Diagnostic]) -> None:
        server.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    watchers_registered = False

    async def validate_and_publish(uri: str) -> None:
        document = server.workspace.get_text_document(uri)
        path = _path_of(uri)
        found = await asyncio.to_thread(backend.validate_file, path, document.source)
        publish(uri, [to_lsp_diagnostic(item) for item in found])

    async def revalidate(uris: Iterable[str]) -> None:
        for uri in uris:
            try:
                await validate_and_publish(uri)
            except Exception:
                _LOG.exception("could not validate %s again", uri)

    def watched_layer_roots() -> list[Path]:
        starts = [Path(to_fs_path(folder.uri)) for folder in server.workspace.folders.values()]
        for uri in server.workspace.text_documents:
            try:
                starts.append(_path_of(uri))
            except ValueError:
                continue
        roots: dict[str, Path] = {}
        for start in starts:
            for layer in backend.chain_layers(start):
                roots.setdefault(os.path.normcase(str(layer.path)), layer.path)
        return list(roots.values())

    async def refresh_watchers() -> None:
        nonlocal watchers_registered
        capability = server.client_capabilities.workspace
        support = capability.did_change_watched_files if capability is not None else None
        if support is None or not support.dynamic_registration:
            return
        try:
            roots = await asyncio.to_thread(watched_layer_roots)
            watchers = watch_patterns(
                roots,
                backend.user_config_file,
                relative_patterns=bool(support.relative_pattern_support),
            )
            if watchers_registered:
                await server.client_unregister_capability_async(
                    types.UnregistrationParams(
                        unregisterations=[
                            types.Unregistration(
                                id=WATCH_REGISTRATION_ID,
                                method=types.WORKSPACE_DID_CHANGE_WATCHED_FILES,
                            )
                        ]
                    )
                )
                watchers_registered = False
            await server.client_register_capability_async(
                types.RegistrationParams(
                    registrations=[
                        types.Registration(
                            id=WATCH_REGISTRATION_ID,
                            method=types.WORKSPACE_DID_CHANGE_WATCHED_FILES,
                            register_options=types.DidChangeWatchedFilesRegistrationOptions(
                                watchers=watchers
                            ),
                        )
                    ]
                )
            )
            watchers_registered = True
        except Exception:
            _LOG.exception("could not register file watchers")

    async def apply_configuration_change() -> None:
        backend.reload_configuration()
        await refresh_watchers()
        await revalidate(list(server.workspace.text_documents))

    @server.feature(types.INITIALIZE)
    def initialize(params: types.InitializeParams) -> None:
        backend.set_editor_settings(editor_settings_from(params.initialization_options))

    @server.feature(types.INITIALIZED)
    async def initialized(params: types.InitializedParams) -> None:
        await refresh_watchers()

    @server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
    async def did_change_configuration(params: types.DidChangeConfigurationParams) -> None:
        backend.set_editor_settings(editor_settings_from(params.settings))
        await apply_configuration_change()

    @server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
    async def did_change_watched_files(params: types.DidChangeWatchedFilesParams) -> None:
        paths = []
        for change in params.changes:
            try:
                paths.append(_path_of(change.uri))
            except ValueError:
                continue
        user_file = backend.user_config_file
        if any(is_configuration_file(path, user_file) for path in paths):
            await apply_configuration_change()
            return
        dependents: set[Path] = set()
        for path in paths:
            dependents |= await asyncio.to_thread(backend.on_file_saved, path)
        affected = list(select_open(server.workspace.text_documents, [*dependents, *paths]))
        if any(path.suffix.casefold() == ".manifest" for path in paths):
            affected = list(server.workspace.text_documents)
        await revalidate(affected)

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(params: types.DidOpenTextDocumentParams) -> None:
        await validate_and_publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: types.DidSaveTextDocumentParams) -> None:
        uri = params.text_document.uri
        dependents = await asyncio.to_thread(backend.on_file_saved, _path_of(uri))
        await validate_and_publish(uri)
        await revalidate(select_open(server.workspace.text_documents, dependents))

    @server.feature(
        types.TEXT_DOCUMENT_CODE_ACTION,
        types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
    )
    async def code_action(params: types.CodeActionParams) -> list[types.CodeAction]:
        listed = [item for item in params.context.diagnostics if item.code == M010]
        if not listed:
            return []
        edit = await asyncio.to_thread(
            backend.manifest_add_edit, _path_of(params.text_document.uri)
        )
        if edit is None:
            return []
        title = f"Add {edit.added[0]} to {edit.manifest_path.name}"
        return [
            types.CodeAction(
                title=title,
                kind=types.CodeActionKind.QuickFix,
                diagnostics=listed,
                edit=to_lsp_workspace_edit(edit),
            )
        ]

    @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
    async def did_close(params: types.DidCloseTextDocumentParams) -> None:
        publish(params.text_document.uri, [])

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=[" ", '"']),
    )
    async def completion(params: types.CompletionParams) -> types.CompletionList:
        document = server.workspace.get_text_document(params.text_document.uri)
        position = Position(params.position.line, params.position.character)
        items = await asyncio.to_thread(
            backend.complete, _path_of(params.text_document.uri), document.source, position
        )
        return types.CompletionList(
            is_incomplete=False, items=[to_lsp_completion(item) for item in items]
        )

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    async def hover(params: types.HoverParams) -> types.Hover | None:
        document = server.workspace.get_text_document(params.text_document.uri)
        position = Position(params.position.line, params.position.character)
        result = await asyncio.to_thread(
            backend.hover, _path_of(params.text_document.uri), document.source, position
        )
        return None if result is None else to_lsp_hover(result)

    @server.feature(types.TEXT_DOCUMENT_DEFINITION)
    async def definition(params: types.DefinitionParams) -> types.Location | None:
        document = server.workspace.get_text_document(params.text_document.uri)
        position = Position(params.position.line, params.position.character)
        result = await asyncio.to_thread(
            backend.definition, _path_of(params.text_document.uri), document.source, position
        )
        return None if result is None else to_lsp_location(result)

    return server


def main() -> None:
    """Run the LSP server over stdio.

    Logging goes to stderr because stdout carries the protocol.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_server().start_io()


if __name__ == "__main__":
    main()
