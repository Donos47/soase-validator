"""Smoke tests for the project scaffolding."""

import importlib
import sys

import pytest

import sose_validator
from sose_validator.cli.main import main as cli_main


def test_package_imports() -> None:
    assert sose_validator.__version__
    assert sys.version_info >= (3, 14)


@pytest.mark.parametrize(
    "module",
    [
        "sose_validator.engine",
        "sose_validator.definitions",
        "sose_validator.audit.audit",
        "sose_validator.lsp.server",
        "sose_validator.mcp_server.app",
    ],
)
def test_modules_import(module: str) -> None:
    importlib.import_module(module)


def test_cli_entry_point_runs() -> None:
    assert cli_main([]) == 0
