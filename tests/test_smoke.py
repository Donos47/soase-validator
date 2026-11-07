"""Smoke tests for the project scaffolding."""

import importlib
import sys

import pytest

import soase_validator
from soase_validator.cli.main import main as cli_main


def test_package_imports() -> None:
    assert soase_validator.__version__
    assert sys.version_info >= (3, 14)


@pytest.mark.parametrize(
    "module",
    [
        "soase_validator.engine",
        "soase_validator.definitions",
        "soase_validator.lsp.server",
        "soase_validator.mcp_server.app",
    ],
)
def test_modules_import(module: str) -> None:
    importlib.import_module(module)


def test_cli_version_flag_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as raised:
        cli_main(["--version"])
    assert raised.value.code == 0
