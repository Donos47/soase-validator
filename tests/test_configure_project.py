"""Tests of first-time project configuration through the Engine facade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.versions import GameVersion

VERSION = GameVersion.REBELLION_198


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return Engine(
        user_config_path=tmp_path / "user" / "config.json",
        env={},
        layer_cache=LayerCache(use_disk=False),
    )


def _read(file: Path) -> dict[str, object]:
    return json.loads(file.read_text(encoding="utf-8"))


def test_fresh_project_creates_file_with_supplied_values(tmp_path: Path, engine: Engine) -> None:
    result = engine.configure_project(
        tmp_path,
        game_version=GameVersion.DIPLOMACY,
        reference_root="~/path/to/ref",
        layers=["@base", "parent"],
        language="de",
    )

    assert result.created is True
    assert result.file == tmp_path / "soase.json"
    assert set(result.set_keys) == {
        "gameVersion",
        "language",
        "layers",
        f"referenceRoots.{GameVersion.DIPLOMACY.value}",
    }
    assert _read(result.file) == {
        "gameVersion": GameVersion.DIPLOMACY.value,
        "language": "de",
        "layers": ["@base", "parent"],
        "referenceRoots": {GameVersion.DIPLOMACY.value: "~/path/to/ref"},
    }
    assert not engine.user_config_file.exists()


def test_no_values_still_creates_an_empty_project_file(tmp_path: Path, engine: Engine) -> None:
    result = engine.configure_project(tmp_path)

    assert result.created is True
    assert result.set_keys == ()
    assert _read(result.file) == {}


def test_reference_root_without_game_version_is_stored_under_rebellion_198(
    tmp_path: Path, engine: Engine
) -> None:
    result = engine.configure_project(tmp_path, reference_root="root")

    assert _read(result.file) == {"referenceRoots": {VERSION.value: "root"}}


def test_reference_root_ignores_the_game_version_already_in_the_file(
    tmp_path: Path, engine: Engine
) -> None:
    file = tmp_path / "soase.json"
    file.write_text(json.dumps({"gameVersion": GameVersion.DIPLOMACY.value}), encoding="utf-8")

    engine.configure_project(tmp_path, reference_root="root")

    assert _read(file) == {
        "gameVersion": GameVersion.DIPLOMACY.value,
        "referenceRoots": {VERSION.value: "root"},
    }


def test_mod_roots_are_written_and_merged_like_other_keys(tmp_path: Path, engine: Engine) -> None:
    file = tmp_path / "soase.json"
    file.write_text(json.dumps({"modRoots": ["a"], "language": "fr"}), encoding="utf-8")

    skipped = engine.configure_project(tmp_path, mod_roots=["b", "c"])
    assert skipped.skipped_keys == ("modRoots",)
    assert _read(file)["modRoots"] == ["a"]

    unchanged = engine.configure_project(tmp_path, mod_roots=["a"])
    assert unchanged.unchanged_keys == ("modRoots",)

    replaced = engine.configure_project(tmp_path, mod_roots=["b", "c"], overwrite=True)
    assert replaced.set_keys == ("modRoots",)
    assert _read(file) == {"modRoots": ["b", "c"], "language": "fr"}


def test_mod_roots_are_resolved_relative_to_the_project_file(
    tmp_path: Path, engine: Engine
) -> None:
    (tmp_path / "content").mkdir()

    engine.configure_project(tmp_path, mod_roots=["content"])

    assert engine.resolve_settings(tmp_path).mod_roots == (tmp_path / "content",)


def test_fresh_project_creates_mod_roots_key(tmp_path: Path, engine: Engine) -> None:
    result = engine.configure_project(tmp_path, mod_roots=["m"])

    assert result.set_keys == ("modRoots",)


def test_user_default_reference_root_is_reported_not_copied(tmp_path: Path, engine: Engine) -> None:
    default = tmp_path / "game"
    engine.set_reference_root(tmp_path, VERSION, str(default), user=True)

    result = engine.configure_project(tmp_path)

    assert result.default_reference_root == default
    assert _read(result.file) == {}


def test_user_default_follows_the_supplied_game_version(tmp_path: Path, engine: Engine) -> None:
    engine.set_reference_root(tmp_path, VERSION, str(tmp_path / "game"), user=True)

    result = engine.configure_project(tmp_path, game_version=GameVersion.DIPLOMACY)

    assert result.default_reference_root is None


def test_no_default_is_reported_when_a_root_is_supplied_or_the_project_defines_one(
    tmp_path: Path, engine: Engine
) -> None:
    engine.set_reference_root(tmp_path, VERSION, str(tmp_path / "game"), user=True)

    supplied = engine.configure_project(tmp_path, reference_root="mine")
    assert supplied.default_reference_root is None

    other = tmp_path / "other"
    other.mkdir()
    (other / "soase.json").write_text(
        json.dumps({"referenceRoots": {VERSION.value: "own"}}), encoding="utf-8"
    )
    defined = engine.configure_project(other)
    assert defined.default_reference_root is None


def test_existing_file_is_merged_and_other_keys_kept(tmp_path: Path, engine: Engine) -> None:
    file = tmp_path / "soase.json"
    file.write_text(
        json.dumps({"disabledCodes": ["SOASE-V001"], "referenceRoots": {"vanilla": "v"}}),
        encoding="utf-8",
    )

    result = engine.configure_project(tmp_path, reference_root="r", language="en")

    assert result.created is False
    assert _read(file) == {
        "disabledCodes": ["SOASE-V001"],
        "referenceRoots": {"vanilla": "v", VERSION.value: "r"},
        "language": "en",
    }


def test_parent_project_file_is_not_touched(tmp_path: Path, engine: Engine) -> None:
    parent = tmp_path / "soase.json"
    parent.write_text('{"language": "fr"}', encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()

    result = engine.configure_project(child, language="de")

    assert result.file == child / "soase.json"
    assert result.created is True
    assert _read(parent) == {"language": "fr"}


def test_conflicting_values_are_skipped_and_equal_values_unchanged(
    tmp_path: Path, engine: Engine
) -> None:
    file = tmp_path / "soase.json"
    file.write_text(
        json.dumps({"language": "fr", "gameVersion": VERSION.value, "layers": ["a"]}),
        encoding="utf-8",
    )

    result = engine.configure_project(tmp_path, game_version=VERSION, language="de", layers=["a"])

    assert result.skipped_keys == ("language",)
    assert result.unchanged_keys == ("gameVersion", "layers")
    assert result.set_keys == ()
    assert _read(file)["language"] == "fr"


def test_overwrite_replaces_differing_values(tmp_path: Path, engine: Engine) -> None:
    file = tmp_path / "soase.json"
    file.write_text(
        json.dumps({"language": "fr", "referenceRoots": {VERSION.value: "old"}}),
        encoding="utf-8",
    )

    result = engine.configure_project(tmp_path, reference_root="new", language="de", overwrite=True)

    assert set(result.set_keys) == {"language", f"referenceRoots.{VERSION.value}"}
    assert result.skipped_keys == ()
    assert _read(file) == {"language": "de", "referenceRoots": {VERSION.value: "new"}}


@pytest.mark.parametrize(
    "arguments",
    [
        {"language": ""},
        {"language": ".hidden"},
        {"language": "a/b"},
        {"layers": ["ok", ""]},
        {"mod_roots": ["ok", " "]},
        {"reference_root": "  "},
    ],
)
def test_invalid_input_writes_nothing(
    tmp_path: Path, engine: Engine, arguments: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        engine.configure_project(tmp_path, game_version=VERSION, **arguments)  # type: ignore[arg-type]

    assert not (tmp_path / "soase.json").exists()


def test_invalid_input_leaves_an_existing_file_unchanged(tmp_path: Path, engine: Engine) -> None:
    file = tmp_path / "soase.json"
    file.write_text('{"language": "fr"}', encoding="utf-8")

    with pytest.raises(ValueError):
        engine.configure_project(tmp_path, game_version=VERSION, layers=[""], overwrite=True)

    assert file.read_text(encoding="utf-8") == '{"language": "fr"}'


def test_unreadable_existing_file_and_missing_directory_are_rejected(
    tmp_path: Path, engine: Engine
) -> None:
    (tmp_path / "soase.json").write_text("{oops", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        engine.configure_project(tmp_path, language="de")
    with pytest.raises(ValueError, match="does not exist"):
        engine.configure_project(tmp_path / "missing", language="de")
    assert (tmp_path / "soase.json").read_text(encoding="utf-8") == "{oops"
