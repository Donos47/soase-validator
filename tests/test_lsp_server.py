"""Protocol-level tests of the LSP server over a loopback TCP connection.

The server runs in a daemon thread with an Engine built over a small test
registry; the pygls client drives it. Every wait has a timeout so a missing
response fails the test instead of hanging it.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from lsprotocol import types
from pygls.lsp.client import LanguageClient
from pygls.uris import from_fs_path

from soase_validator.engine import diagnostics as dg
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.lsp.server import create_server

TIMEOUT = 15.0
BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'
ENTITY_STUB = 'TXT2\nSinsArchiveVersion 194\nentityType "Stub"\n'
ENTITY_ENUMS = {"enums": [{"name": "entityType", "values": ["Stub"]}]}


def _engine(tmp_path: Path) -> Engine:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [{"node": "field", "name": "b", "validation": "Brush"}],
        },
        {"name": "Stub", "children": []},
    ]
    texts = {
        "s.json": json.dumps({"structures": structures}),
        "enums.json": json.dumps(ENTITY_ENUMS),
    }
    return Engine(
        user_config_path=tmp_path / "no-user-file.json",
        env={},
        layer_cache=LayerCache(use_disk=False),
        registry=load_registry_from_texts(texts),
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _foo(brush: str) -> str:
    return f'TXT\nb "{brush}"\n'


def _uri(path: Path) -> str:
    uri = from_fs_path(str(path))
    assert uri is not None
    return uri


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _Session:
    """A connected client with helpers for documents and published diagnostics."""

    def __init__(self, client: LanguageClient) -> None:
        self.client = client
        self.published: dict[str, asyncio.Queue[list[types.Diagnostic]]] = {}

    def queue(self, uri: str) -> asyncio.Queue[list[types.Diagnostic]]:
        return self.published.setdefault(uri, asyncio.Queue())

    async def next_codes(self, path: Path) -> list[str]:
        """Wait for the next publication for a file and return its codes."""
        found = await asyncio.wait_for(self.queue(_uri(path)).get(), TIMEOUT)
        return [str(item.code) for item in found]

    async def open(self, path: Path, text: str | None = None) -> list[str]:
        """Open a document and return the codes of the first publication."""
        content = path.read_text(encoding="utf-8") if text is None else text
        self.client.text_document_did_open(
            types.DidOpenTextDocumentParams(
                text_document=types.TextDocumentItem(
                    uri=_uri(path), language_id="soase", version=1, text=content
                )
            )
        )
        return await self.next_codes(path)

    def change(self, path: Path, text: str, version: int) -> None:
        self.client.text_document_did_change(
            types.DidChangeTextDocumentParams(
                text_document=types.VersionedTextDocumentIdentifier(
                    uri=_uri(path), version=version
                ),
                content_changes=[types.TextDocumentContentChangeWholeDocument(text=text)],
            )
        )

    def save(self, path: Path) -> None:
        self.client.text_document_did_save(
            types.DidSaveTextDocumentParams(text_document=types.TextDocumentIdentifier(_uri(path)))
        )

    def close(self, path: Path) -> None:
        self.client.text_document_did_close(
            types.DidCloseTextDocumentParams(text_document=types.TextDocumentIdentifier(_uri(path)))
        )

    def identifier(self, path: Path) -> types.TextDocumentIdentifier:
        return types.TextDocumentIdentifier(_uri(path))


@asynccontextmanager
async def _connected(
    engine: Engine, settings: dict[str, Any] | None = None
) -> AsyncIterator[_Session]:
    port = _free_port()
    server = create_server(engine)
    thread = threading.Thread(
        target=server.start_tcp, args=("127.0.0.1", port), name="lsp-test-server", daemon=True
    )
    thread.start()
    client = LanguageClient("test-client", "0")
    session = _Session(client)

    @client.feature(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    def on_publish(params: types.PublishDiagnosticsParams) -> None:
        session.queue(params.uri).put_nowait(list(params.diagnostics))

    deadline = asyncio.get_running_loop().time() + TIMEOUT
    while True:
        try:
            await client.start_tcp("127.0.0.1", port)
            break
        except OSError:
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(
            client.initialize_async(
                types.InitializeParams(
                    capabilities=types.ClientCapabilities(), initialization_options=settings
                )
            ),
            TIMEOUT,
        )
        client.initialized(types.InitializedParams())
        yield session
    finally:
        try:
            await asyncio.wait_for(client.shutdown_async(None), TIMEOUT)
        finally:
            client._stop_event.set()
            for task in client._async_tasks:
                task.cancel()


def _run(scenario: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(asyncio.wait_for(scenario(), TIMEOUT * 4))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project above a parent mod that defines ``ParentBrush``."""
    _write(tmp_path / "parent", "Window/p.brushes", BRUSHES.format(name="ParentBrush"))
    _write(tmp_path / "project", "soase.json", json.dumps({"layers": ["../parent"]}))
    return tmp_path / "project"


def test_open_publishes_and_close_clears(tmp_path: Path, project: Path) -> None:
    bad = _write(project, "bad.foo", _foo("Gone"))
    good = _write(project, "good.foo", _foo("ParentBrush"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await session.open(bad) == [dg.R010]
            assert await session.open(good) == []
            session.close(bad)
            assert await session.next_codes(bad) == []

    _run(scenario)


def test_publication_uses_zero_based_ranges_and_the_code_catalogue(
    tmp_path: Path, project: Path
) -> None:
    bad = _write(project, "bad.foo", _foo("Gone"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            session.client.text_document_did_open(
                types.DidOpenTextDocumentParams(
                    text_document=types.TextDocumentItem(
                        uri=_uri(bad), language_id="soase", version=1, text=_foo("Gone")
                    )
                )
            )
            found = await asyncio.wait_for(session.queue(_uri(bad)).get(), TIMEOUT)
            assert [item.code for item in found] == [dg.R010]
            assert found[0].range.start.line == 1
            assert found[0].severity is types.DiagnosticSeverity.Error
            assert found[0].source == "soase-validator"

    _run(scenario)


def test_fix_then_save_clears_the_diagnostic(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("Gone"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await session.open(file) == [dg.R010]
            file.write_text(_foo("ParentBrush"), encoding="utf-8", newline="\n")
            session.change(file, _foo("ParentBrush"), 2)
            session.save(file)
            assert await session.next_codes(file) == []

    _run(scenario)


def test_save_of_a_parent_file_revalidates_open_dependents(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("Later"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await session.open(file) == [dg.R010]
            added = _write(
                tmp_path / "parent", "Window/later.brushes", BRUSHES.format(name="Later")
            )
            session.client.workspace_did_change_watched_files(
                types.DidChangeWatchedFilesParams(
                    changes=[types.FileEvent(uri=_uri(added), type=types.FileChangeType.Created)]
                )
            )
            assert await session.next_codes(file) == []

    _run(scenario)


def test_completion_returns_chain_names(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", "")

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            text = 'TXT\nb "Par"\n'
            await session.open(file, text)
            result = await asyncio.wait_for(
                session.client.text_document_completion_async(
                    types.CompletionParams(
                        text_document=session.identifier(file),
                        position=types.Position(line=1, character=6),
                    )
                ),
                TIMEOUT,
            )
            assert isinstance(result, types.CompletionList)
            assert [item.label for item in result.items] == ["ParentBrush"]

    _run(scenario)


def test_hover_returns_markdown_or_nothing(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("ParentBrush"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            await session.open(file)
            hovered = await asyncio.wait_for(
                session.client.text_document_hover_async(
                    types.HoverParams(
                        text_document=session.identifier(file),
                        position=types.Position(line=1, character=0),
                    )
                ),
                TIMEOUT,
            )
            assert hovered is not None
            assert isinstance(hovered.contents, types.MarkupContent)
            assert hovered.contents.kind is types.MarkupKind.Markdown
            blank = await asyncio.wait_for(
                session.client.text_document_hover_async(
                    types.HoverParams(
                        text_document=session.identifier(file),
                        position=types.Position(line=5, character=0),
                    )
                ),
                TIMEOUT,
            )
            assert blank is None

    _run(scenario)


def test_definition_points_into_the_parent_layer(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("ParentBrush"))
    target = tmp_path / "parent" / "Window" / "p.brushes"

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            await session.open(file)
            found = await asyncio.wait_for(
                session.client.text_document_definition_async(
                    types.DefinitionParams(
                        text_document=session.identifier(file),
                        position=types.Position(line=1, character=5),
                    )
                ),
                TIMEOUT,
            )
            assert isinstance(found, types.Location)
            assert found.uri == _uri(target)

    _run(scenario)


def _manifest_project(root: Path) -> tuple[Path, Path]:
    _write(root, "soase.json", "{}")
    manifest = _write(root, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(root, "GameInfo/a.entity", ENTITY_STUB)
    unlisted = _write(root, "GameInfo/b.entity", ENTITY_STUB)
    return manifest, unlisted


async def _actions(session: _Session, path: Path) -> list[types.CodeAction]:
    codes = await session.open(path)
    assert codes == [dg.M010]
    context_items = [
        types.Diagnostic(
            range=types.Range(types.Position(0, 0), types.Position(0, 0)),
            message="m",
            code=dg.M010,
        )
    ]
    result = await asyncio.wait_for(
        session.client.text_document_code_action_async(
            types.CodeActionParams(
                text_document=session.identifier(path),
                range=types.Range(types.Position(0, 0), types.Position(0, 0)),
                context=types.CodeActionContext(diagnostics=context_items),
            )
        ),
        TIMEOUT,
    )
    return [item for item in result or [] if isinstance(item, types.CodeAction)]


def test_add_to_manifest_action_edits_the_project_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    manifest, unlisted = _manifest_project(project)

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            actions = await _actions(session, unlisted)
            assert len(actions) == 1
            assert actions[0].kind == types.CodeActionKind.QuickFix
            assert actions[0].edit is not None and actions[0].edit.changes is not None
            edits = actions[0].edit.changes[_uri(manifest)]
            original = manifest.read_text(encoding="utf-8")
            assert len(edits) == 1
            assert edits[0].range.start == types.Position(0, 0)
            assert edits[0].range.end == types.Position(line=original.count("\n"), character=0)
            assert edits[0].new_text == (
                'TXT\nentityNameCount 2\nentityName "a.entity"\nentityName "b.entity"\n'
            )

    _run(scenario)


def test_no_action_without_an_m010_diagnostic(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _, unlisted = _manifest_project(project)

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            await session.open(unlisted)
            result = await asyncio.wait_for(
                session.client.text_document_code_action_async(
                    types.CodeActionParams(
                        text_document=session.identifier(unlisted),
                        range=types.Range(types.Position(0, 0), types.Position(0, 0)),
                        context=types.CodeActionContext(diagnostics=[]),
                    )
                ),
                TIMEOUT,
            )
            assert not result

    _run(scenario)


def test_no_action_when_the_governing_manifest_is_in_a_parent_layer(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    _write(parent, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "a.entity"\n')
    _write(parent, "GameInfo/a.entity", ENTITY_STUB)
    overlay = tmp_path / "overlay"
    _write(overlay, "soase.json", json.dumps({"layers": ["../parent"]}))
    added = _write(overlay, "GameInfo/b.entity", ENTITY_STUB)

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await _actions(session, added) == []

    _run(scenario)


def test_watched_soase_json_change_revalidates_open_files(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("Gone"))
    config_file = project / "soase.json"

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await session.open(file) == [dg.R010]
            config_file.write_text(
                json.dumps({"layers": ["../parent"], "disabledCodes": [dg.R010]}),
                encoding="utf-8",
            )
            session.client.workspace_did_change_watched_files(
                types.DidChangeWatchedFilesParams(
                    changes=[
                        types.FileEvent(uri=_uri(config_file), type=types.FileChangeType.Changed)
                    ]
                )
            )
            assert await session.next_codes(file) == []

    _run(scenario)


def test_did_change_configuration_applies_editor_settings(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("Gone"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path)) as session:
            assert await session.open(file) == [dg.R010]
            session.client.workspace_did_change_configuration(
                types.DidChangeConfigurationParams(
                    settings={"soase-validator": {"disabledCodes": [dg.R010]}}
                )
            )
            assert await session.next_codes(file) == []

    _run(scenario)


def test_initialization_options_are_editor_settings(tmp_path: Path, project: Path) -> None:
    file = _write(project, "a.foo", _foo("Gone"))

    async def scenario() -> None:
        async with _connected(_engine(tmp_path), {"disabledCodes": [dg.R010]}) as session:
            assert await session.open(file) == []

    _run(scenario)
