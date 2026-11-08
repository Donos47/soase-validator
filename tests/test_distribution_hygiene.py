"""Smoke tests for entry points, offline operation and repository hygiene."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import soase_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src" / "soase_validator"
TIMEOUT = 60

ENTRY_POINTS = {
    "soase-validator": "soase_validator.cli.main:main",
    "soase-validator-lsp": "soase_validator.lsp.server:main",
    "soase-validator-mcp": "soase_validator.mcp_server.app:main",
}

ASSET_EXTENSIONS = {".mesh", ".dds", ".ogg"}

NETWORK_MODULES = (
    "socket",
    "ssl",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "requests",
    "httpx",
    "aiohttp",
    "websockets",
)

# Replaces outbound connection primitives before the entry point runs. Loopback
# connections stay allowed because asyncio builds its self-pipe from them.
OFFLINE_PREAMBLE = """
import socket, sys

_connect = socket.socket.connect

def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise OSError("network access is not permitted")
    return _connect(self, address)

def _refuse(*args, **kwargs):
    raise OSError("network access is not permitted")

socket.socket.connect = _guarded_connect
socket.getaddrinfo = _refuse
socket.create_connection = _refuse

module, func = sys.argv[1].split(":")
sys.argv = [sys.argv[1]] + sys.argv[2:]
getattr(__import__(module, fromlist=[func]), func)()
"""


def _tracked_files() -> list[Path]:
    """List git-tracked files relative to the repository root.

    Returns:
        The tracked paths.

    Raises:
        pytest.skip.Exception: When git or the repository metadata is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=TIMEOUT,
        )
    except OSError, subprocess.SubprocessError:
        pytest.skip("git metadata is unavailable")
    return [Path(name) for name in result.stdout.decode("utf-8").split("\0") if name]


def _launch(target: str, *args: str) -> subprocess.Popen[bytes]:
    """Start an entry point target in a subprocess with the offline guard.

    Args:
        target: The `module:function` entry point target.
        *args: Extra command-line arguments.

    Returns:
        The running process with piped standard streams.
    """
    return subprocess.Popen(
        [sys.executable, "-c", OFFLINE_PREAMBLE, target, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )


def _initialize_request() -> dict[str, object]:
    """Build a JSON-RPC initialize request.

    Returns:
        The request payload.
    """
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "processId": None,
            "rootUri": None,
            "capabilities": {},
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "smoke-test", "version": "0"},
        },
    }


def _finish(process: subprocess.Popen[bytes]) -> bytes:
    """Close an entry point process and collect its standard error.

    Args:
        process: The process to close.

    Returns:
        The captured standard error output.
    """
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    process.stdout.close()
    stderr = process.stderr.read()
    process.stderr.close()
    return stderr


def test_package_imports_with_version() -> None:
    assert soase_validator.__version__


def test_declared_entry_points_match_the_spec() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"] == ENTRY_POINTS


def test_cli_entry_point_answers_offline() -> None:
    process = _launch(ENTRY_POINTS["soase-validator"], "--version")
    stdout, stderr = process.communicate(timeout=TIMEOUT)
    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    assert soase_validator.__version__ in stdout.decode("utf-8")


def test_lsp_entry_point_answers_initialize_offline() -> None:
    process = _launch(ENTRY_POINTS["soase-validator-lsp"])
    assert process.stdin is not None
    assert process.stdout is not None
    body = json.dumps(_initialize_request()).encode("utf-8")
    process.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    process.stdin.flush()
    try:
        length = 0
        while line := process.stdout.readline().strip():
            name, _, value = line.decode("ascii").partition(":")
            if name.lower() == "content-length":
                length = int(value)
        assert length > 0
        reply = json.loads(process.stdout.read(length))
    finally:
        stderr = _finish(process)
    assert reply["id"] == 1, stderr.decode("utf-8", "replace")
    assert "capabilities" in reply["result"]
    assert reply["result"]["serverInfo"]["name"]


def test_mcp_entry_point_answers_initialize_offline() -> None:
    process = _launch(ENTRY_POINTS["soase-validator-mcp"])
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(_initialize_request()).encode("utf-8") + b"\n")
    process.stdin.flush()
    try:
        reply = json.loads(process.stdout.readline())
    finally:
        stderr = _finish(process)
    assert reply["id"] == 1, stderr.decode("utf-8", "replace")
    assert "capabilities" in reply["result"]
    assert reply["result"]["serverInfo"]["name"]


def test_source_imports_no_network_modules() -> None:
    names = "|".join(NETWORK_MODULES)
    pattern = re.compile(rf"^\s*(?:import|from)\s+(?:{names})\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_repository_tracks_no_binary_game_assets() -> None:
    offenders = [str(path) for path in _tracked_files() if path.suffix.lower() in ASSET_EXTENSIONS]
    assert offenders == []


def test_tracked_entity_files_are_confined_to_fixtures() -> None:
    offenders = [
        str(path)
        for path in _tracked_files()
        if path.suffix.lower() == ".entity" and "fixtures" not in path.parts
    ]
    assert offenders == []


def test_reference_material_is_not_tracked() -> None:
    offenders = [
        str(path) for path in _tracked_files() if path.parts[0] in {"reference", "audit-output"}
    ]
    assert offenders == []
