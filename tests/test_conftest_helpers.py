"""Tests for the shared test helpers."""

import pytest
from hypothesis import settings

from conftest import build_mod_tree, find_reference_root, reference_root_env_var


def test_hypothesis_profile_runs_at_least_100_examples() -> None:
    assert settings().max_examples >= 100


def test_mod_tree_factory_writes_files(mod_tree) -> None:
    root = mod_tree({"Entity/a.entity": "TXT\n", "String/en.str": "x"})
    assert (root / "Entity" / "a.entity").read_text(encoding="utf-8") == "TXT\n"
    assert (root / "String" / "en.str").is_file()


def test_build_mod_tree_rejects_escaping_paths(tmp_path) -> None:
    with pytest.raises(ValueError):
        build_mod_tree(tmp_path / "m", {"../evil.txt": ""})


def test_find_reference_root_reads_env(monkeypatch, tmp_path) -> None:
    var = reference_root_env_var("rebellion_198")
    assert var == "SOASE_REFERENCE_ROOT_REBELLION_198"
    monkeypatch.delenv(var, raising=False)
    assert find_reference_root("REBELLION_198") is None
    monkeypatch.setenv(var, str(tmp_path))
    assert find_reference_root("REBELLION_198") == tmp_path
