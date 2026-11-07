"""Unit tests for settings resolution and configuration writers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.engine.config import (
    SourceKind,
    add_layer,
    effective_config,
    expand_path,
    remove_layer,
    remove_reference_root,
    resolve_settings,
    set_alias,
    set_layers,
    set_reference_root,
)
from soase_validator.engine.model import Severity
from soase_validator.engine.versions import GameVersion


def _write(path: Path, data: object) -> Path:
    """Write JSON to a file, creating parents.

    Args:
        path: Destination.
        data: JSON-compatible content.

    Returns:
        The path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def user_file(tmp_path: Path) -> Path:
    """Return a user-level file path that does not exist yet."""
    return tmp_path / "userdir" / "config.json"


def test_defaults_without_any_file(tmp_path: Path, user_file: Path) -> None:
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "Entity.MANIFEST").write_text("TXT\n", encoding="utf-8")
    (mod / "Entity").mkdir()

    settings = resolve_settings(mod / "Entity", env={}, user_file=user_file)

    assert settings.game_version is GameVersion.REBELLION_198
    assert settings.mod_roots == (mod,)
    assert settings.disabled_codes == frozenset()
    assert settings.sources["gameVersion"].kind is SourceKind.DEFAULT
    assert settings.problems == ()


def test_default_mod_root_without_manifest_or_project(tmp_path: Path, user_file: Path) -> None:
    settings = resolve_settings(tmp_path / "a" / "b.entity", env={}, user_file=user_file)
    assert settings.mod_roots == ()


def test_nearest_project_file_wins_and_falls_through(tmp_path: Path, user_file: Path) -> None:
    _write(tmp_path / "soase.json", {"gameVersion": "vanilla", "disabledCodes": ["soase-c030"]})
    inner = tmp_path / "overlay"
    _write(inner / "soase.json", {"gameVersion": "diplomacy"})

    settings = resolve_settings(inner / "x.entity", env={}, user_file=user_file)

    assert settings.game_version is GameVersion.DIPLOMACY
    assert settings.sources["gameVersion"].path == inner / "soase.json"
    assert settings.disabled_codes == frozenset({"SOASE-C030"})
    assert settings.sources["disabledCodes"].path == tmp_path / "soase.json"
    assert settings.project_file == inner / "soase.json"


def test_precedence_project_env_editor_user(tmp_path: Path, user_file: Path) -> None:
    _write(user_file, {"gameVersion": "vanilla"})
    env = {"SOASE_VALIDATOR_GAME_VERSION": "entrenchment"}
    editor = {"gameVersion": "diplomacy"}

    user_only = resolve_settings(tmp_path, env={}, user_file=user_file)
    with_editor = resolve_settings(tmp_path, editor, env={}, user_file=user_file)
    with_env = resolve_settings(tmp_path, editor, env=env, user_file=user_file)
    _write(tmp_path / "soase.json", {"gameVersion": "rebellion-193"})
    with_project = resolve_settings(tmp_path, editor, env=env, user_file=user_file)

    assert (user_only.game_version, user_only.sources["gameVersion"].kind) == (
        GameVersion.VANILLA,
        SourceKind.USER,
    )
    assert with_editor.game_version is GameVersion.DIPLOMACY
    assert with_editor.sources["gameVersion"].kind is SourceKind.EDITOR
    assert with_env.game_version is GameVersion.ENTRENCHMENT
    assert with_env.sources["gameVersion"].kind is SourceKind.ENVIRONMENT
    assert with_project.game_version is GameVersion.REBELLION_193
    assert with_project.sources["gameVersion"].kind is SourceKind.PROJECT


def test_reference_roots_resolve_per_version(tmp_path: Path, user_file: Path) -> None:
    _write(user_file, {"defaultReferenceRoots": {"rebellion-1.98": "user-root", "vanilla": "v"}})
    _write(tmp_path / "soase.json", {"referenceRoots": {"rebellion": "proj-root"}})
    env = {"SOASE_REFERENCE_ROOT_DIPLOMACY": "env-root"}

    settings = resolve_settings(tmp_path, env=env, user_file=user_file)

    roots = settings.reference_roots
    assert roots[GameVersion.REBELLION_198] == tmp_path / "proj-root"
    assert roots[GameVersion.DIPLOMACY] == tmp_path / "env-root"
    assert roots[GameVersion.VANILLA] == user_file.parent / "v"
    assert settings.sources["referenceRoots.vanilla"].kind is SourceKind.USER
    assert GameVersion.ENTRENCHMENT not in roots


def test_invalid_settings_report_problem_and_use_default(tmp_path: Path, user_file: Path) -> None:
    _write(
        tmp_path / "soase.json",
        {
            "gameVersion": "sins2",
            "numeric": {"integerStrict": "yes", "decimalAllowInteger": False},
            "manifest": {"unreferencedSeverity": "loud"},
            "disabledCodes": "SOASE-C030",
            "reportOverrides": True,
        },
    )

    settings = resolve_settings(tmp_path, env={}, user_file=user_file)

    names = {p.setting for p in settings.problems}
    assert names == {
        "gameVersion",
        "numeric.integerStrict",
        "manifest.unreferencedSeverity",
        "disabledCodes",
    }
    assert settings.game_version is GameVersion.REBELLION_198
    assert settings.numeric.integer_strict is False
    assert settings.numeric.decimal_allow_integer is False
    assert settings.manifest.unreferenced_severity is Severity.INFO
    assert settings.disabled_codes == frozenset()
    assert settings.report_overrides is True


def test_non_object_section_is_reported_once(tmp_path: Path, user_file: Path) -> None:
    _write(tmp_path / "soase.json", {"numeric": 3})

    settings = resolve_settings(tmp_path, env={}, user_file=user_file)

    assert [p.setting for p in settings.problems] == ["numeric"]


def test_unreadable_json_is_reported_and_skipped(tmp_path: Path, user_file: Path) -> None:
    (tmp_path / "soase.json").write_text("{not json", encoding="utf-8")
    _write(user_file, {"gameVersion": "vanilla"})

    settings = resolve_settings(tmp_path, env={}, user_file=user_file)

    assert settings.problems[0].setting == "soase.json"
    assert settings.game_version is GameVersion.VANILLA


def test_relative_paths_resolve_against_containing_file(
    tmp_path: Path, user_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    _write(project / "soase.json", {"modRoots": [".", "sub"], "layers": ["../parent", "@base"]})
    monkeypatch.chdir(tmp_path)

    settings = resolve_settings(project / "x.entity", env={}, user_file=user_file)

    assert settings.mod_roots == (project, project / "sub")
    assert settings.layer_specs == (str(tmp_path / "parent"), "@base")


def test_expand_path_handles_home_and_variables(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path / "home"), "ROOT": str(tmp_path / "r")}

    assert expand_path("~/a", tmp_path, env) == tmp_path / "home" / "a"
    assert expand_path("%ROOT%/b", tmp_path, env) == tmp_path / "r" / "b"
    assert expand_path("$ROOT/c", tmp_path, env) == tmp_path / "r" / "c"
    assert expand_path("${ROOT}/d", tmp_path, env) == tmp_path / "r" / "d"
    assert expand_path("rel", tmp_path, env) == tmp_path / "rel"
    with pytest.raises(ValueError, match="empty"):
        expand_path(" ", tmp_path, env)


def test_aliases_manifest_prefs_and_editor_paths(tmp_path: Path, user_file: Path) -> None:
    _write(user_file, {"aliases": {"@e4x": "layers/e4x", "bad": 3}})
    editor = {
        "manifest": {
            "unreferencedSeverity": "warning",
            "exemptUnlisted": ["Foo*"],
            "exemptUnreferenced": ["Bar*"],
        },
        "suppressLimitedReferenceNotice": True,
    }

    settings = resolve_settings(tmp_path, editor, env={}, user_file=user_file)

    assert settings.aliases == {"e4x": user_file.parent / "layers" / "e4x"}
    assert [p.setting for p in settings.problems] == ["aliases.bad"]
    assert settings.manifest.unreferenced_severity is Severity.WARNING
    assert settings.manifest.exempt_unlisted == ("Foo*",)
    assert settings.manifest.exempt_unreferenced == ("Bar*",)
    assert settings.suppress_limited_notice is True


def test_effective_config_reports_sources_and_found_roots(tmp_path: Path, user_file: Path) -> None:
    present = tmp_path / "game"
    present.mkdir()
    _write(
        tmp_path / "soase.json",
        {"referenceRoots": {"rebellion-1.98": "game", "vanilla": "missing"}},
    )

    report = effective_config(tmp_path, env={}, user_file=user_file)

    by_name = {e.name: e for e in report.entries}
    assert by_name["referenceRoots.rebellion-1.98"].source.kind is SourceKind.PROJECT
    assert by_name["gameVersion"].source.kind is SourceKind.DEFAULT
    assert report.reference_roots_found == {"rebellion-1.98": True, "vanilla": False}
    assert report.project_files == (tmp_path / "soase.json",)
    assert report.user_file == user_file


def test_set_reference_root_preserves_other_keys(tmp_path: Path) -> None:
    file = _write(tmp_path / "soase.json", {"layers": ["x"]})

    set_reference_root(file, GameVersion.REBELLION_198, "~/path/to/ref")

    data = json.loads(file.read_text(encoding="utf-8"))
    assert data == {"layers": ["x"], "referenceRoots": {"rebellion-1.98": "~/path/to/ref"}}
    assert remove_reference_root(file, GameVersion.REBELLION_198) is True
    assert remove_reference_root(file, GameVersion.REBELLION_198) is False


def test_user_reference_root_and_alias_written_and_read_back(
    tmp_path: Path, user_file: Path
) -> None:
    set_reference_root(user_file, GameVersion.VANILLA, "vanilla-root", user=True)
    set_alias(user_file, "@e4x", "e4x-path")

    settings = resolve_settings(tmp_path, env={}, user_file=user_file)

    assert settings.reference_roots[GameVersion.VANILLA] == user_file.parent / "vanilla-root"
    assert settings.aliases["e4x"] == user_file.parent / "e4x-path"


def test_layer_helpers_add_move_remove_replace(tmp_path: Path) -> None:
    file = tmp_path / "soase.json"

    add_layer(file, "a")
    add_layer(file, "@b")
    add_layer(file, "c", 0)
    add_layer(file, "a")
    assert json.loads(file.read_text(encoding="utf-8"))["layers"] == ["c", "@b", "a"]
    assert remove_layer(file, "@b") is True
    assert remove_layer(file, "@b") is False
    set_layers(file, ["z", "y"])
    assert json.loads(file.read_text(encoding="utf-8"))["layers"] == ["z", "y"]
    with pytest.raises(ValueError, match="empty"):
        add_layer(file, "")


def test_writers_reject_invalid_existing_file(tmp_path: Path) -> None:
    file = tmp_path / "soase.json"
    file.write_text("[1]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        set_reference_root(file, GameVersion.VANILLA, "x")
    file.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        add_layer(file, "x")
    assert file.read_text(encoding="utf-8") == "{oops"
