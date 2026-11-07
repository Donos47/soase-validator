"""Tests of the MCP server core tools through the SDK in-memory client."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.model import Diagnostic, Position, Range, Severity
from soase_validator.engine.registry import load_registry_from_texts, structure_to_json
from soase_validator.engine.versions import GameVersion, unverified_tokens
from soase_validator.mcp_server.app import create_server, diagnostic_to_dict

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'
BAD_FOO = "TXT\nunknownKey 1\n"
MANIFEST = "TXT2\nSinsArchiveVersion 194\nbrushCount 0\n"


def _engine(tmp_path: Path) -> Engine:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "help": "Root help.",
            "children": [{"node": "field", "name": "b", "validation": "Brush", "help": "A b."}],
        }
    ]
    return Engine(
        user_config_path=tmp_path / "no-user-file.json",
        env={},
        layer_cache=LayerCache(use_disk=False),
        registry=load_registry_from_texts({"s.json": json.dumps({"structures": structures})}),
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _call(engine: Engine, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(create_server(engine)) as client:
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            assert result.structured_content is not None
            return result.structured_content

    return asyncio.run(run())


def test_tools_are_registered(tmp_path: Path) -> None:
    async def run() -> set[str]:
        async with Client(create_server(_engine(tmp_path))) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert asyncio.run(run()) == {
        "validate_file",
        "validate_directory",
        "complete",
        "field_help",
        "list_entity_types",
        "manifest_check",
        "manifest_sync",
        "get_config",
        "set_reference_root",
        "edit_layers",
        "configure",
        "versions",
    }


def test_validate_file_matches_engine_with_one_based_positions(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    file = _write(tmp_path, "a.foo", BAD_FOO)

    result = _call(engine, "validate_file", {"path": str(file)})
    expected = engine.validate_file(file)

    assert expected
    assert len(result["diagnostics"]) == len(expected)
    first = result["diagnostics"][0]
    assert set(first) >= {"file", "line", "column", "severity", "code", "message"}
    assert first["code"] == expected[0].code
    assert first["line"] == expected[0].range.start.line + 1
    assert first["column"] == expected[0].range.start.col + 1
    assert first["severity"] == expected[0].severity.value


def test_validate_file_uses_supplied_text(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    file = _write(tmp_path, "a.foo", "TXT\n")

    clean = _call(engine, "validate_file", {"path": str(file)})
    dirty = _call(engine, "validate_file", {"path": str(file), "text": BAD_FOO})

    assert clean["diagnostics"] == []
    assert dirty["diagnostics"]


def test_validate_directory_groups_by_file(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    bad = _write(tmp_path, "bad.foo", BAD_FOO)
    good = _write(tmp_path, "good.foo", "TXT\n")

    result = _call(engine, "validate_directory", {"path": str(tmp_path)})

    assert result["files"][str(good)] == []
    assert result["files"][str(bad)]


def test_complete_uses_one_based_position(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    file = _write(tmp_path, "a.foo", "TXT\n")

    result = _call(engine, "complete", {"path": str(file), "line": 2, "column": 1})
    expected = engine.complete(file, "TXT\n", Position(1, 0))

    assert [item["label"] for item in result["items"]] == [item.label for item in expected]
    assert "b" in [item["label"] for item in result["items"]]


def test_field_help_and_entity_types(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    found = _call(
        engine, "field_help", {"structure": "Root", "field": "b", "game_version": "rebellion-1.98"}
    )
    missing = _call(
        engine, "field_help", {"structure": "Root", "field": "zz", "game_version": "rebellion-1.98"}
    )
    types = _call(engine, "list_entity_types", {"game_version": "rebellion-1.98"})

    assert found["found"] is True
    assert found["help"]["help"] == "A b."
    assert missing == {"found": False, "help": None}
    assert types["entity_types"] == engine.entity_types(GameVersion.REBELLION_198)


def test_manifest_sync_is_dry_run_by_default(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    manifest = _write(tmp_path, "entity.manifest", "TXT2\nSinsArchiveVersion 194\nentityCount 0\n")
    _write(tmp_path, "GameInfo/x.brushes", BRUSHES.format(name="a"))
    _write(tmp_path, "GameInfo/ship.entity", "TXT\n")
    before = manifest.read_text(encoding="utf-8")

    checked = _call(engine, "manifest_check", {"path": str(tmp_path)})
    dry = _call(engine, "manifest_sync", {"path": str(tmp_path)})

    assert dry["dry_run"] is True
    assert dry["backups"] == []
    assert manifest.read_text(encoding="utf-8") == before
    assert isinstance(checked["diagnostics"], list)

    written = _call(engine, "manifest_sync", {"path": str(tmp_path), "write": True})
    assert written["dry_run"] is False
    assert written["edits"]
    assert len(written["backups"]) == len(written["edits"])


def test_definition_resource(tmp_path: Path) -> None:
    async def run() -> tuple[Any, Any]:
        async with Client(create_server(_engine(tmp_path))) as client:
            ok = await client.read_resource("soase://definitions/Root")
            try:
                bad = await client.read_resource("soase://definitions/Nope")
            except Exception as error:
                bad = error
            return ok, bad

    ok, bad = asyncio.run(run())
    data = json.loads(ok.contents[0].text)
    assert data["name"] == "Root"
    assert data["children"][0]["name"] == "b"
    assert isinstance(bad, Exception)


def _fail(engine: Engine, tool: str, arguments: dict[str, Any]) -> bool:
    async def run() -> bool:
        async with Client(create_server(engine)) as client:
            return (await client.call_tool(tool, arguments)).is_error

    return asyncio.run(run())


def test_set_reference_root_writes_project_file_and_get_config_reports_it(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    (tmp_path / "base").mkdir()

    written = _call(
        engine,
        "set_reference_root",
        {"game_version": "rebellion-1.98", "root": "../base", "path": str(project)},
    )
    report = _call(engine, "get_config", {"path": str(project)})

    assert Path(written["file"]) == project / "soase.json"
    assert written["found"] is True
    assert json.loads((project / "soase.json").read_text(encoding="utf-8")) == {
        "referenceRoots": {"rebellion-1.98": "../base"}
    }
    setting = next(s for s in report["settings"] if s["name"] == "referenceRoots.rebellion-1.98")
    assert setting["source"] == "project"
    assert setting["source_file"] == str(project / "soase.json")
    assert report["reference_roots_found"] == {"rebellion-1.98": True}
    assert [layer["kind"] for layer in report["chain"]][0] == "game"
    assert all(layer["found"] for layer in report["chain"])


def test_set_reference_root_reports_missing_directory_and_user_scope(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    user_file = engine.user_config_file

    written = _call(
        engine,
        "set_reference_root",
        {
            "game_version": "rebellion-1.98",
            "root": str(tmp_path / "absent"),
            "path": str(tmp_path),
            "user": True,
        },
    )

    assert Path(written["file"]) == user_file
    assert written["found"] is False
    assert "defaultReferenceRoots" in json.loads(user_file.read_text(encoding="utf-8"))
    assert not (tmp_path / "soase.json").exists()
    assert _fail(
        engine, "set_reference_root", {"game_version": "nope", "root": "x", "path": str(tmp_path)}
    )


def test_edit_layers_add_move_reorder_remove(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    base = {"path": str(tmp_path)}

    added = _call(engine, "edit_layers", {"action": "add", "layers": ["a", "b", "c"], **base})
    assert added["layers"] == ["a", "b", "c"]
    names = [layer["name"] for layer in added["chain"]]
    assert names.index("a") < names.index("b") < names.index("c")
    assert all(layer["found"] for layer in added["chain"])

    moved = _call(engine, "edit_layers", {"action": "move", "layers": ["c"], "index": 0, **base})
    assert moved["layers"] == ["c", "a", "b"]

    reordered = _call(
        engine, "edit_layers", {"action": "reorder", "layers": ["b", "c", "a"], **base}
    )
    assert reordered["layers"] == ["b", "c", "a"]

    removed = _call(engine, "edit_layers", {"action": "remove", "layers": ["c"], **base})
    assert removed["layers"] == ["b", "a"]
    saved = json.loads((tmp_path / "soase.json").read_text(encoding="utf-8"))
    assert saved["layers"] == ["b", "a"]


def test_edit_layers_reports_missing_layer_and_rejects_bad_requests(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    base = {"path": str(tmp_path)}

    added = _call(engine, "edit_layers", {"action": "add", "layers": ["gone"], **base})

    assert [layer["found"] for layer in added["chain"] if layer["name"] == "gone"] == [False]
    assert _fail(engine, "edit_layers", {"action": "reorder", "layers": ["x"], **base})
    assert _fail(engine, "edit_layers", {"action": "remove", "layers": ["nope"], **base})
    assert _fail(engine, "edit_layers", {"action": "move", "layers": ["gone"], **base})
    assert _fail(engine, "edit_layers", {"action": "swap", "layers": ["gone"], **base})


def _tools(engine: Engine) -> dict[str, Any]:
    """Return the registered tool functions by name for direct calls."""
    server = create_server(engine)
    names = (
        "validate_file",
        "validate_directory",
        "complete",
        "field_help",
        "list_entity_types",
        "manifest_check",
        "manifest_sync",
        "get_config",
        "set_reference_root",
        "edit_layers",
        "configure",
        "versions",
    )
    return {name: server._tool_manager.get_tool(name).fn for name in names}


def _diagnostic(
    file: Path, start: tuple[int, int], end: tuple[int, int], severity: Severity = Severity.ERROR
) -> Diagnostic:
    return Diagnostic(
        file=file,
        range=Range(Position(*start), Position(*end)),
        severity=severity,
        code="SOASE-V001",
        message="message",
    )


def test_diagnostic_to_dict_converts_to_one_based_positions(tmp_path: Path) -> None:
    file = tmp_path / "a.foo"

    result = diagnostic_to_dict(_diagnostic(file, (0, 0), (2, 4), Severity.WARNING))

    assert result == {
        "file": str(file),
        "line": 1,
        "column": 1,
        "end_line": 3,
        "end_column": 5,
        "severity": "warning",
        "code": "SOASE-V001",
        "message": "message",
    }
    assert json.loads(json.dumps(result)) == result


def test_structure_to_json_is_json_serializable_and_omits_unset_attributes() -> None:
    registry = load_registry_from_texts(
        {
            "s.json": json.dumps(
                {
                    "structures": [
                        {
                            "name": "Root",
                            "extension": ".foo",
                            "help": "Root help.",
                            "children": [{"node": "field", "name": "b", "validation": "Brush"}],
                        },
                        {"name": "Bare", "children": []},
                    ]
                }
            )
        }
    )

    root = registry.structure("Root")
    bare = registry.structure("Bare")
    assert root is not None
    assert bare is not None
    data = structure_to_json(root)

    assert json.loads(json.dumps(data)) == data
    assert data["name"] == "Root"
    assert data["extension"] == ".foo"
    assert data["children"][0]["name"] == "b"
    assert structure_to_json(bare) == {"name": "Bare", "children": []}


def test_direct_tool_calls_match_the_client_results(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    file = _write(tmp_path, "a.foo", BAD_FOO)
    tools = _tools(engine)

    assert tools["validate_file"](str(file)) == _call(engine, "validate_file", {"path": str(file)})
    assert tools["validate_directory"](str(tmp_path)) == _call(
        engine, "validate_directory", {"path": str(tmp_path)}
    )
    assert tools["complete"](str(file), 2, 1, "TXT\n") == _call(
        engine, "complete", {"path": str(file), "line": 2, "column": 1, "text": "TXT\n"}
    )
    arguments = {"structure": "Root", "field": "b", "game_version": "rebellion-1.98"}
    assert tools["field_help"](**arguments) == _call(engine, "field_help", arguments)
    assert tools["list_entity_types"]("rebellion-1.98") == _call(
        engine, "list_entity_types", {"game_version": "rebellion-1.98"}
    )
    assert tools["manifest_check"](str(tmp_path)) == _call(
        engine, "manifest_check", {"path": str(tmp_path)}
    )
    assert tools["manifest_sync"](str(tmp_path)) == _call(
        engine, "manifest_sync", {"path": str(tmp_path)}
    )
    assert tools["get_config"](str(tmp_path)) == _call(
        engine, "get_config", {"path": str(tmp_path)}
    )


def test_direct_config_tools_write_project_files(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    (tmp_path / "base").mkdir()
    (project / "a").mkdir()
    tools = _tools(engine)

    written = tools["set_reference_root"]("rebellion-1.98", "../base", str(project))
    edited = tools["edit_layers"]("add", ["a"], None, str(project))

    assert written["found"] is True
    assert edited["layers"] == ["a"]
    saved = json.loads((project / "soase.json").read_text(encoding="utf-8"))
    assert saved["layers"] == ["a"]
    assert saved["referenceRoots"] == {"rebellion-1.98": "../base"}


def test_configure_creates_project_file_and_reports_effective_config(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    (tmp_path / "base").mkdir()

    result = _call(
        engine,
        "configure",
        {
            "path": str(project),
            "game_version": "rebellion-1.98",
            "reference_root": "../base",
            "layers": ["parent"],
            "language": "de",
        },
    )

    assert result["created"] is True
    assert result["file"] == str(project / "soase.json")
    assert set(result["set"]) == {
        "gameVersion",
        "language",
        "layers",
        "referenceRoots.rebellion-1.98",
    }
    assert result["skipped"] == []
    assert result["config"]["reference_roots_found"] == {"rebellion-1.98": True}
    assert [layer["found"] for layer in result["config"]["chain"] if layer["name"] == "parent"] == [
        False
    ]
    saved = json.loads((project / "soase.json").read_text(encoding="utf-8"))
    assert saved["language"] == "de"
    assert saved["layers"] == ["parent"]


def test_configure_skips_conflicts_until_overwrite(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    file = tmp_path / "soase.json"
    file.write_text('{"language": "fr", "disabledCodes": ["SOASE-V001"]}', encoding="utf-8")
    arguments = {"path": str(tmp_path), "language": "de", "layers": ["a"]}

    first = _call(engine, "configure", arguments)
    assert first["created"] is False
    assert first["skipped"] == ["language"]
    assert first["set"] == ["layers"]

    second = _call(engine, "configure", {**arguments, "overwrite": True})
    assert second["set"] == ["language"]
    assert second["unchanged"] == ["layers"]
    saved = json.loads(file.read_text(encoding="utf-8"))
    assert saved["language"] == "de"
    assert saved["disabledCodes"] == ["SOASE-V001"]


def test_configure_writes_mod_roots_and_reports_the_user_default_root(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    default = tmp_path / "game"
    engine.set_reference_root(project, GameVersion.REBELLION_198, str(default), user=True)

    result = _call(engine, "configure", {"path": str(project), "mod_roots": ["content"]})

    assert result["set"] == ["modRoots"]
    assert result["default_reference_root"] == str(default)
    saved = json.loads((project / "soase.json").read_text(encoding="utf-8"))
    assert saved == {"modRoots": ["content"]}


def test_configure_rejects_blank_mod_roots(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    assert _fail(engine, "configure", {"path": str(tmp_path), "mod_roots": [" "]})
    assert not (tmp_path / "soase.json").exists()


def test_direct_configure_uses_the_working_directory_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    monkeypatch.chdir(project)

    result = _tools(engine)["configure"](language="en")

    assert result["file"] == str(project / "soase.json")
    assert result["set"] == ["language"]


def test_configure_rejects_bad_input_and_writes_nothing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    base = {"path": str(tmp_path)}

    assert _fail(engine, "configure", {**base, "game_version": "nope"})
    assert _fail(engine, "configure", {**base, "language": "../x"})
    assert _fail(engine, "configure", {**base, "layers": ["ok", " "]})
    assert _fail(engine, "configure", {**base, "reference_root": " "})
    assert _fail(engine, "configure", {"path": str(tmp_path / "missing")})
    assert not (tmp_path / "soase.json").exists()


def test_direct_tools_reject_bad_arguments(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    file = _write(tmp_path, "a.foo", "TXT\n")
    tools = _tools(engine)

    with pytest.raises(ValueError, match="unknown game version"):
        tools["field_help"]("Root", "b", "nope")
    with pytest.raises(ValueError, match="unknown game version"):
        tools["list_entity_types"]("nope")
    with pytest.raises(ValueError, match="unknown game version"):
        tools["set_reference_root"]("nope", "x", str(tmp_path))
    for line, column in ((0, 1), (1, 0), (-1, -1)):
        with pytest.raises(ValueError, match="one-based"):
            tools["complete"](str(file), line, column)


def test_error_paths_through_the_client(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    file = _write(tmp_path, "a.foo", "TXT\n")
    path = str(file)

    assert _fail(engine, "field_help", {"structure": "Root", "field": "b", "game_version": "x"})
    assert _fail(engine, "list_entity_types", {"game_version": "x"})
    assert _fail(engine, "complete", {"path": path, "line": 0, "column": 1})
    assert _fail(engine, "complete", {"path": path, "line": 1, "column": 0})
    unknown = _call(
        engine, "field_help", {"structure": "Nope", "field": "b", "game_version": "rebellion-1.98"}
    )
    assert unknown == {"found": False, "help": None}


def test_get_config_without_any_configuration(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "empty"
    project.mkdir()

    report = _call(engine, "get_config", {"path": str(project)})

    assert report["project_files"] == []
    assert not Path(report["user_file"]).exists()
    assert report["problems"] == []
    assert report["reference_roots_found"] == {}
    assert all(setting["source"] == "default" for setting in report["settings"])
    assert report["chain"] == []


def test_diagnostics_are_identical_to_the_engine(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    _write(tmp_path, "bad.foo", BAD_FOO)
    _write(tmp_path, "good.foo", "TXT\n")
    _write(tmp_path, "entity.manifest", "TXT2\nSinsArchiveVersion 194\nentityCount 0\n")
    _write(tmp_path, "GameInfo/ship.entity", "TXT\n")

    directory = _call(engine, "validate_directory", {"path": str(tmp_path)})
    manifests = _call(engine, "manifest_check", {"path": str(tmp_path)})

    expected_directory = {
        str(file): [diagnostic_to_dict(item) for item in found]
        for file, found in engine.validate_directory(tmp_path).items()
    }
    expected_manifests = [diagnostic_to_dict(item) for item in engine.manifest_check(tmp_path)]
    assert directory["files"] == expected_directory
    assert any(directory["files"].values())
    assert manifests["diagnostics"] == expected_manifests
    assert expected_manifests


def test_tools_leave_stdout_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    engine = _engine(tmp_path)
    (tmp_path / "soase.json").write_text("{}", encoding="utf-8")
    file = _write(tmp_path, "a.foo", BAD_FOO)
    capsys.readouterr()

    tools = _tools(engine)
    tools["validate_file"](str(file))
    tools["validate_directory"](str(tmp_path))
    tools["get_config"](str(tmp_path))
    _call(engine, "manifest_check", {"path": str(tmp_path)})

    assert capsys.readouterr().out == ""


def test_versions_lists_audit_status_and_unverified_tokens(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    result = _call(engine, "versions", {})

    by_id = {item["id"]: item for item in result["versions"]}
    assert [item["id"] for item in result["versions"]] == [
        "vanilla",
        "entrenchment",
        "diplomacy",
        "rebellion-185",
        "rebellion-193",
        "rebellion-194",
        "rebellion-1.98",
    ]
    assert by_id["rebellion-1.98"]["audit_status"] == "audited"
    assert by_id["rebellion-1.98"]["label"] == "audited"
    assert by_id["rebellion-194"]["audit_status"] == "unaudited"
    assert by_id["vanilla"]["label"] == "unaudited, best-effort"
    assert result["unverified_tokens"] == list(unverified_tokens())
    assert _tools(engine)["versions"]() == result


def test_manifest_sync_reports_lower_layer_advisories_without_editing_them(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    manifest = _write(
        base, "entity.manifest", 'TXT\nentityNameCount 1\nentityName "reserved.entity"\n'
    )
    _write(overlay, "GameInfo/extra.entity", "TXT\n")
    _write(overlay, "soase.json", json.dumps({"layers": [str(base)]}))
    before = manifest.read_bytes()

    for write in (False, True):
        result = _call(engine, "manifest_sync", {"path": str(overlay), "write": write})

        assert result["edits"] == []
        assert result["advisories"] == [
            {"manifest": str(manifest), "layer": "base", "names": ["extra.entity"]}
        ]
        assert "extra.entity" in result["diff"]
        assert manifest.read_bytes() == before


def test_set_reference_root_warns_when_the_directory_holds_no_game_data(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "notes").mkdir()
    (tmp_path / "game" / "gameinfo").mkdir(parents=True)

    plain = _call(
        engine,
        "set_reference_root",
        {"game_version": "rebellion-1.98", "root": "../plain", "path": str(project)},
    )
    game = _call(
        engine,
        "set_reference_root",
        {"game_version": "rebellion-1.98", "root": "../game", "path": str(project)},
    )
    absent = _call(
        engine,
        "set_reference_root",
        {"game_version": "rebellion-1.98", "root": "../absent", "path": str(project)},
    )

    assert plain["found"] is True
    assert plain["warnings"] == [
        {
            "code": "SOASE-C020",
            "message": (
                f"Reference Root does not look like a game data directory: {tmp_path / 'plain'}"
            ),
            "path": str(tmp_path / "plain"),
        }
    ]
    assert game["warnings"] == []
    assert absent["found"] is False
    assert [w["message"] for w in absent["warnings"]] == [
        f"Reference Root does not exist: {tmp_path / 'absent'}"
    ]
    saved = json.loads((project / "soase.json").read_text(encoding="utf-8"))
    assert saved["referenceRoots"] == {"rebellion-1.98": "../absent"}


def test_configure_warns_when_the_reference_root_holds_no_game_data(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    project = tmp_path / "mod"
    project.mkdir()
    (tmp_path / "plain").mkdir()

    result = _call(engine, "configure", {"path": str(project), "reference_root": "../plain"})
    quiet = _call(engine, "configure", {"path": str(project), "language": "en"})

    assert [w["code"] for w in result["warnings"]] == ["SOASE-C020"]
    assert result["warnings"][0]["path"] == str(tmp_path / "plain")
    assert "does not look like a game data directory" in result["warnings"][0]["message"]
    assert "referenceRoots.rebellion-1.98" in result["set"]
    assert [layer["status"] for layer in result["config"]["chain"] if layer["kind"] == "game"] == [
        "unusable"
    ]
    assert quiet["warnings"] == []
