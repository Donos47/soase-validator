"""Tests for the ``validate`` command."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from soase_validator.cli.main import main
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.mcp_server.app import create_server

BRUSHES = 'TXT2\nSinsArchiveVersion 194\nbrushCount 1\nbrush\n\tname "{name}"\n'
BAD_FOO = "TXT\nunknownKey 1\n"


def _engine(tmp_path: Path) -> Engine:
    structures = [
        {
            "name": "Root",
            "extension": ".foo",
            "children": [{"node": "field", "name": "b", "validation": "Brush"}],
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


def _project(tmp_path: Path, **settings: object) -> Path:
    root = tmp_path / "project"
    _write(root, "soase.json", json.dumps(settings))
    return root


def _call(engine: Engine, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(create_server(engine)) as client:
            result = await client.call_tool(tool, arguments)
            assert result.structured_content is not None
            return result.structured_content

    return asyncio.run(run())


def _json_diagnostics(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return json.loads(capsys.readouterr().out)["diagnostics"]


def test_a_file_gives_the_diagnostics_of_the_mcp_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    file = _write(project, "a.foo", BAD_FOO)

    code = main(["validate", str(file), "--format", "json"], _engine(tmp_path))

    expected = _call(_engine(tmp_path), "validate_file", {"path": str(file)})["diagnostics"]
    assert expected
    assert code == 1
    assert _json_diagnostics(capsys) == expected


def test_a_directory_gives_the_diagnostics_of_the_mcp_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write(project, "bad.foo", BAD_FOO)
    _write(project, "good.foo", "TXT\n")

    code = main(["validate", str(project), "--format", "json"], _engine(tmp_path))

    files = _call(_engine(tmp_path), "validate_directory", {"path": str(project)})["files"]
    expected = [item for found in files.values() for item in found]
    assert expected
    assert code == 1
    assert _json_diagnostics(capsys) == expected


def test_json_items_carry_the_mcp_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    file = _write(project, "a.foo", BAD_FOO)

    main(["validate", str(file), "--format", "json"], _engine(tmp_path))

    first = _json_diagnostics(capsys)[0]
    assert set(first) >= {"file", "line", "column", "severity", "code", "message"}
    assert first["file"] == str(file)
    assert first["code"] == "SOASE-V020"
    assert first["line"] == 2 and first["column"] >= 1


def test_text_lines_use_one_based_positions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    file = _write(project, "a.foo", BAD_FOO)
    found = _engine(tmp_path).validate_file(file)[0]

    code = main(["validate", str(file)], _engine(tmp_path))

    captured = capsys.readouterr()
    start = found.range.start
    expected = (
        f"{file}:{start.line + 1}:{start.col + 1}: "
        f"{found.severity.value} {found.code} {found.message}"
    )
    assert code == 1
    assert captured.out.splitlines() == [expected]
    assert "1 diagnostics, 1 errors" in captured.err


def test_clean_input_exits_zero_with_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    file = _write(project, "a.foo", "TXT\n")

    code = main(["validate", str(file)], _engine(tmp_path))

    assert code == 0
    assert capsys.readouterr().out == ""


def test_warnings_alone_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path, layers=["../missing-parent"])
    file = _write(project, "a.foo", "TXT\n")

    code = main(["validate", str(file), "--format", "json"], _engine(tmp_path))

    severities = {item["severity"] for item in _json_diagnostics(capsys)}
    assert "warning" in severities
    assert "error" not in severities
    assert code == 0


def test_a_missing_path_is_reported_on_stderr_with_a_non_zero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.foo"

    code = main(["validate", str(missing)], _engine(tmp_path))

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert f"error: path does not exist: {missing}" in captured.err


def test_an_unknown_game_version_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)

    code = main(["validate", str(project), "--game-version", "nope"], _engine(tmp_path))

    assert code != 0
    assert "unknown game version 'nope'" in capsys.readouterr().err


def test_a_known_game_version_is_accepted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write(project, "a.foo", "TXT\n")

    code = main(["validate", str(project), "--game-version", "vanilla"], _engine(tmp_path))

    assert code == 0


def test_without_paths_the_path_option_selects_the_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write(project, "a.foo", BAD_FOO)

    code = main(["validate", "--path", str(project)], _engine(tmp_path))

    assert code == 1
    assert "SOASE-V020" in capsys.readouterr().out


def test_without_a_reference_root_unresolved_references_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parent = tmp_path / "parent"
    _write(parent, "Window/p.brushes", BRUSHES.format(name="ParentBrush"))
    project = _project(tmp_path, layers=["../parent"])
    good = _write(project, "good.foo", 'TXT\nb "ParentBrush"\n')
    bad = _write(project, "bad.foo", 'TXT\nb "BaseGameBrush"\n')

    code = main(["validate", str(project), "--format", "json"], _engine(tmp_path))

    found = {(item["file"], item["code"]) for item in _json_diagnostics(capsys)}
    assert (str(bad), "SOASE-R010") in found
    assert not any(file == str(good) for file, _ in found)
    assert code == 1


def test_a_reference_to_a_base_game_name_is_unresolved_for_the_project_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    bad = _write(project, "bad.foo", 'TXT\nb "BaseGameBrush"\n')

    code = main(["validate", str(bad)], _engine(tmp_path))

    assert code == 1
    assert "SOASE-R010" in capsys.readouterr().out
