"""Shared pytest fixtures and helpers for sose-validator tests."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

# Hypothesis profile: every property test runs at least 100 examples.
settings.register_profile(
    "sose",
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
settings.load_profile("sose")

DEFAULT_REFERENCE_VERSION = "REBELLION_196"


def reference_root_env_var(version: str) -> str:
    """Return the environment variable name holding a Reference Root path.

    Args:
        version: Game Version token such as ``REBELLION_196``.

    Returns:
        The variable name, for example ``SOSE_REFERENCE_ROOT_REBELLION_196``.
    """
    return f"SOSE_REFERENCE_ROOT_{version.upper()}"


def find_reference_root(version: str = DEFAULT_REFERENCE_VERSION) -> Path | None:
    """Locate a Reference Root for a Game Version from the environment.

    Args:
        version: Game Version token such as ``REBELLION_196``.

    Returns:
        The directory path, or None when unset or not an existing directory.
    """
    value = os.environ.get(reference_root_env_var(version))
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


def build_mod_tree(root: Path, files: Mapping[str, str] | None = None) -> Path:
    """Create a small synthetic mod tree on disk.

    Args:
        root: Directory to create the tree in (created if missing).
        files: Mapping of relative POSIX paths to text content.

    Returns:
        The ``root`` path.

    Raises:
        ValueError: If a relative path is absolute or escapes ``root``.
    """
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve()
    for rel, content in (files or {}).items():
        target = (root / rel).resolve()
        if not target.is_relative_to(resolved_root) or Path(rel).is_absolute():
            raise ValueError(f"path escapes the mod tree: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def reference_root() -> Path:
    """Reference Root for Rebellion 1.96; skips the test when unavailable."""
    path = find_reference_root(DEFAULT_REFERENCE_VERSION)
    if path is None:
        pytest.skip(
            f"no Reference Root: set {reference_root_env_var(DEFAULT_REFERENCE_VERSION)} "
            "to a directory containing the game files"
        )
    return path


@pytest.fixture
def mod_tree(tmp_path: Path) -> Callable[..., Path]:
    """Factory building synthetic mod trees under ``tmp_path``.

    Call as ``mod_tree({"Entity/a.entity": "..."}, name="mod")``.
    """

    def _factory(files: Mapping[str, str] | None = None, name: str = "mod") -> Path:
        return build_mod_tree(tmp_path / name, files)

    return _factory
