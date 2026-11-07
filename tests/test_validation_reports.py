"""Tests for validation reports written by the CLI and the MCP server."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.shared.exceptions import MCPError

from soase_validator.cli.main import main
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.registry import load_registry_from_texts
from soase_validator.mcp_server.app import create_server
from soase_validator.reports import build_report, write_report

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


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _write(root, "soase.json", "{}")
    _write(root, "good.foo", "TXT\n")
    _write(root, "bad.foo", BAD_FOO)
    _write(root, "worse.foo", "TXT\nunknownKey 1\nother 2\n")
    return root


def _call(engine: Engine, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(create_server(engine)) as client:
            result = await client.call_tool(tool, arguments)
            assert result.structured_content is not None
            return result.structured_content

    return asyncio.run(run())


def test_json_report_lists_only_files_with_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    report = tmp_path / "report.json"

    code = main(
        ["validate", str(project), "--format", "json", "--output", str(report)], _engine(tmp_path)
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 1
    assert data["files_validated"] == 3
    assert data["files_with_findings"] == 2
    assert set(data["files"]) == {str(project / "bad.foo"), str(project / "worse.foo")}
    assert data["counts"] == {"error": 3, "warning": 0, "info": 0}
    assert data["by_code"] == {"SOASE-V020": 3}
    assert set(data["files"][str(project / "bad.foo")][0]) >= {"line", "column", "end_line"}
    assert capsys.readouterr().out.strip() == (
        f"3 files validated, 3 errors, 0 warnings, 0 info; report: {report}"
    )


def test_text_report_has_lines_and_a_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    report = tmp_path / "report.txt"

    main(["validate", str(project), "--output", str(report)], _engine(tmp_path))

    lines = report.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert lines[0].startswith(f"{project / 'bad.foo'}:2:1: error SOASE-V020 ")
    assert lines[-1] == "3 files validated, 3 errors, 0 warnings, 0 info"
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_exit_status_matches_the_run_without_output(tmp_path: Path) -> None:
    project = _project(tmp_path)
    clean = tmp_path / "clean"
    _write(clean, "soase.json", "{}")
    _write(clean, "good.foo", "TXT\n")

    failing = main(
        ["validate", str(project), "--output", str(tmp_path / "a.txt")], _engine(tmp_path)
    )
    passing = main(["validate", str(clean), "--output", str(tmp_path / "b.txt")], _engine(tmp_path))

    assert (failing, passing) == (1, 0)


def test_an_existing_report_is_overwritten(tmp_path: Path) -> None:
    project = _project(tmp_path)
    report = tmp_path / "report.txt"
    report.write_text("old content\n", encoding="utf-8")

    main(["validate", str(project), "--output", str(report)], _engine(tmp_path))

    assert "old content" not in report.read_text(encoding="utf-8")


def test_a_missing_parent_directory_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    report = tmp_path / "missing" / "report.json"

    code = main(["validate", str(project), "--output", str(report)], _engine(tmp_path))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "directory does not exist" in captured.err
    assert not report.exists()


def test_several_paths_merge_into_one_report(tmp_path: Path) -> None:
    project = _project(tmp_path)
    report = tmp_path / "report.json"

    main(
        [
            "validate",
            str(project / "bad.foo"),
            str(project / "good.foo"),
            "--format",
            "json",
            "--output",
            str(report),
        ],
        _engine(tmp_path),
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["files_validated"] == 2
    assert list(data["files"]) == [str(project / "bad.foo")]


def test_a_file_outside_every_mod_root_is_a_finding_but_not_validated(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    file = _write(folder, "Test.foo", BAD_FOO)
    report = tmp_path / "report.json"

    code = main(
        ["validate", str(file), "--format", "json", "--output", str(report)], _engine(tmp_path)
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0
    assert data["files_validated"] == 0
    assert data["by_code"] == {"SOASE-C050": 1}
    assert data["counts"]["warning"] == 1


def test_a_report_inside_the_project_is_not_validated_next_time(tmp_path: Path) -> None:
    project = _project(tmp_path)
    report = project / "report.json"
    args = ["validate", str(project), "--format", "json", "--output", str(report)]

    main(args, _engine(tmp_path))
    first = json.loads(report.read_text(encoding="utf-8"))
    main(args, _engine(tmp_path))
    second = json.loads(report.read_text(encoding="utf-8"))

    assert second == first
    assert str(report) not in second["files"]


def test_mcp_summary_fields_and_top_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    report = tmp_path / "report.json"

    result = _call(
        _engine(tmp_path),
        "validate_directory",
        {"path": str(project), "output_path": str(report)},
    )

    assert result == {
        "report": str(report),
        "files_validated": 3,
        "files_with_findings": 2,
        "counts": {"error": 3, "warning": 0, "info": 0},
        "by_code": {"SOASE-V020": 3},
        "top_files": [
            {"file": str(project / "worse.foo"), "count": 2},
            {"file": str(project / "bad.foo"), "count": 1},
        ],
    }


def test_top_files_are_capped_and_ties_sort_by_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project, "soase.json", "{}")
    for index in range(12):
        _write(project, f"f{index:02d}.foo", BAD_FOO)
    report = tmp_path / "report.json"

    result = _call(
        _engine(tmp_path),
        "validate_directory",
        {"path": str(project), "output_path": str(report)},
    )

    names = [Path(item["file"]).name for item in result["top_files"]]
    assert names == [f"f{index:02d}.foo" for index in range(10)]
    assert result["files_with_findings"] == 12


def test_mcp_report_equals_the_cli_json_report(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cli_report = tmp_path / "cli.json"
    mcp_report = tmp_path / "mcp.json"

    main(
        ["validate", str(project), "--format", "json", "--output", str(cli_report)],
        _engine(tmp_path),
    )
    _call(
        _engine(tmp_path),
        "validate_directory",
        {"path": str(project), "output_path": str(mcp_report)},
    )

    assert mcp_report.read_bytes() == cli_report.read_bytes()


def test_mcp_result_is_unchanged_without_output_path(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = _call(_engine(tmp_path), "validate_directory", {"path": str(project)})

    assert set(result) == {"files"}
    assert result["files"][str(project / "good.foo")] == []


def test_mcp_missing_parent_directory_is_a_tool_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    report = tmp_path / "missing" / "report.json"

    async def run() -> bool:
        async with Client(create_server(_engine(tmp_path))) as client:
            try:
                result = await client.call_tool(
                    "validate_directory", {"path": str(project), "output_path": str(report)}
                )
            except MCPError:
                return True
            return bool(result.is_error)

    assert asyncio.run(run())
    assert not report.exists()


def test_a_failed_write_leaves_the_existing_report_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    report.write_text("keep me\n", encoding="utf-8")

    def fail(*_: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)

    with pytest.raises(OSError, match="replace failed"):
        write_report(report, "new content\n")

    assert report.read_text(encoding="utf-8") == "keep me\n"
    assert [item.name for item in tmp_path.iterdir()] == ["report.json"]


def test_an_empty_result_gives_an_empty_report() -> None:
    report = build_report({})

    assert report.files_validated == 0
    assert report.files == {}
    assert report.counts == {"error": 0, "warning": 0, "info": 0}
