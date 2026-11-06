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
        "soase_validator.audit.audit",
        "soase_validator.lsp.server",
        "soase_validator.mcp_server.app",
    ],
)
def test_modules_import(module: str) -> None:
    importlib.import_module(module)


def test_cli_entry_point_runs() -> None:
    assert cli_main([]) == 0
