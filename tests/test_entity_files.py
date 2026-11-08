"""Tests that ``.entity`` files reach the validator through every front end."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from soase_validator.cli.main import main
from soase_validator.engine import diagnostics as dg
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.mcp_server.app import create_server

MANIFEST = 'TXT\nentityNameCount 1\nentityName "Probe.entity"\n'
BAD_ENTITY = 'TXT\nentityType "Buff"\nunknownKey 1\n'


def _engine(tmp_path: Path) -> Engine:
    return Engine(
        user_config_path=tmp_path / "no-user-file.json",
        env={},
        layer_cache=LayerCache(use_disk=False),
    )


def _mod(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "mod"
    (root / "GameInfo").mkdir(parents=True)
    (root / "entity.manifest").write_text(MANIFEST, encoding="utf-8", newline="\n")
    entity = root / "GameInfo" / "Probe.entity"
    entity.write_text(BAD_ENTITY, encoding="utf-8", newline="\n")
    return root, entity


def _unknown_keys(codes: list[str]) -> int:
    return codes.count(dg.V020)


def test_validate_file_checks_an_entity_file(tmp_path: Path) -> None:
    _, entity = _mod(tmp_path)

    found = _engine(tmp_path).validate_file(entity)

    assert _unknown_keys([d.code for d in found]) == 1


def test_validate_directory_includes_entity_files(tmp_path: Path) -> None:
    root, entity = _mod(tmp_path)

    results = _engine(tmp_path).validate_directory(root)

    assert entity in results
    assert _unknown_keys([d.code for d in results[entity]]) == 1


def test_the_cli_reports_entity_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _mod(tmp_path)

    code = main(["validate", str(root), "--format", "json"], _engine(tmp_path))

    codes = [item["code"] for item in json.loads(capsys.readouterr().out)["diagnostics"]]
    assert code == 1
    assert _unknown_keys(codes) == 1


def test_the_mcp_tool_reports_entity_findings(tmp_path: Path) -> None:
    _, entity = _mod(tmp_path)

    async def run() -> dict[str, Any]:
        async with Client(create_server(_engine(tmp_path))) as client:
            result = await client.call_tool("validate_file", {"path": str(entity)})
            assert result.structured_content is not None
            return result.structured_content

    codes = [item["code"] for item in asyncio.run(run())["diagnostics"]]
    assert _unknown_keys(codes) == 1
