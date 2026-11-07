"""Unit tests for the LSP type conversions."""

from __future__ import annotations

from pathlib import Path

import pytest
from lsprotocol import types
from pygls.uris import from_fs_path, to_fs_path

from soase_validator.engine.manifests import ManifestEdit
from soase_validator.engine.model import Diagnostic, Position, Range, Severity
from soase_validator.lsp.server import (
    create_server,
    editor_settings_from,
    is_configuration_file,
    select_open,
    text_end_position,
    to_lsp_diagnostic,
    to_lsp_workspace_edit,
    watch_patterns,
)


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (Severity.ERROR, types.DiagnosticSeverity.Error),
        (Severity.WARNING, types.DiagnosticSeverity.Warning),
        (Severity.INFO, types.DiagnosticSeverity.Information),
    ],
)
def test_diagnostic_conversion_keeps_zero_based_positions(
    severity: Severity, expected: types.DiagnosticSeverity
) -> None:
    """Severity maps one to one and positions are not shifted."""
    source = Diagnostic(
        Path("a.entity"), Range(Position(2, 3), Position(2, 9)), severity, "SOASE-V020", "bad"
    )
    result = to_lsp_diagnostic(source)
    assert result.severity == expected
    assert result.code == "SOASE-V020"
    assert (result.range.start.line, result.range.start.character) == (2, 3)
    assert (result.range.end.line, result.range.end.character) == (2, 9)


def test_create_server_registers_handlers() -> None:
    """The server registers the document and language feature handlers."""
    server = create_server()
    features = server.protocol.fm.features
    for method in (
        types.TEXT_DOCUMENT_DID_OPEN,
        types.TEXT_DOCUMENT_DID_SAVE,
        types.TEXT_DOCUMENT_DID_CLOSE,
        types.TEXT_DOCUMENT_COMPLETION,
        types.TEXT_DOCUMENT_HOVER,
        types.TEXT_DOCUMENT_DEFINITION,
    ):
        assert method in features


def test_create_server_registers_code_action_configuration_and_watch_handlers() -> None:
    """The server registers the handlers for code actions and reloads."""
    features = create_server().protocol.fm.features
    for method in (
        types.TEXT_DOCUMENT_CODE_ACTION,
        types.WORKSPACE_DID_CHANGE_CONFIGURATION,
        types.WORKSPACE_DID_CHANGE_WATCHED_FILES,
        types.INITIALIZE,
        types.INITIALIZED,
    ):
        assert method in features


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, {}),
        ("text", {}),
        ({"language": "de"}, {"language": "de"}),
        ({"soase-validator": {"language": "de"}, "other": 1}, {"language": "de"}),
    ],
)
def test_editor_settings_are_taken_from_the_server_section_or_the_payload(
    payload: object, expected: dict[str, object]
) -> None:
    """A ``soase-validator`` section wins; a plain mapping is used as is."""
    assert editor_settings_from(payload) == expected


@pytest.mark.parametrize(
    ("text", "line", "character"),
    [
        ("", 0, 0),
        ("abc", 0, 3),
        ("abc\n", 1, 0),
        ("a\r\nbc", 1, 2),
        ("a\rb\r", 2, 0),
        ("\U0001f600", 0, 2),
    ],
)
def test_text_end_position_counts_utf16_units(text: str, line: int, character: int) -> None:
    """The end position follows the last line break and counts UTF-16 units."""
    position = text_end_position(text)
    assert (position.line, position.character) == (line, character)


def test_workspace_edit_replaces_the_whole_manifest(tmp_path: Path) -> None:
    """The edit targets the manifest URI with one whole-text replacement."""
    manifest = tmp_path / "entity.manifest"
    edit = ManifestEdit(manifest, "TXT\nold\n", "TXT\nnew\n", ("n",), ())
    result = to_lsp_workspace_edit(edit)
    assert result.changes is not None
    [(uri, edits)] = result.changes.items()
    assert Path(to_fs_path(uri)) == manifest
    assert edits[0].new_text == "TXT\nnew\n"
    assert (edits[0].range.start.line, edits[0].range.start.character) == (0, 0)
    assert (edits[0].range.end.line, edits[0].range.end.character) == (2, 0)


def test_configuration_files_are_soase_json_and_the_user_file(tmp_path: Path) -> None:
    """Any ``soase.json`` and the user file count as configuration."""
    user = tmp_path / "user" / "config.json"
    assert is_configuration_file(tmp_path / "mod" / "SOASE.json", user)
    assert is_configuration_file(user, user)
    assert not is_configuration_file(tmp_path / "mod" / "a.entity", user)


def test_watch_patterns_cover_configuration_and_layers(tmp_path: Path) -> None:
    """Layers are watched recursively next to ``soase.json`` and the user file."""
    root = tmp_path / "layer"
    user = tmp_path / "user" / "config.json"
    relative = watch_patterns([root, root], user, relative_patterns=True)
    patterns = [w.glob_pattern for w in relative]
    assert patterns[0] == "**/soase.json"
    assert [p.pattern for p in patterns[1:]] == ["**/*", "config.json"]
    plain = watch_patterns([root], user, relative_patterns=False)
    assert plain[1].glob_pattern == f"{root.as_posix()}/**/*"


def test_select_open_matches_files_ignoring_uri_spelling(tmp_path: Path) -> None:
    """Open documents are matched by path, and non-file URIs are skipped."""
    target = tmp_path / "a.entity"
    other = tmp_path / "b.entity"
    uris = [from_fs_path(str(target)), from_fs_path(str(other)), "untitled:one"]
    assert select_open(uris, [target]) == [uris[0]]
