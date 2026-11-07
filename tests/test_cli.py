"""Tests for the command-line front end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soase_validator.cli.main import main
from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache
from soase_validator.engine.registry import load_registry_from_texts


def _engine(tmp_path: Path) -> Engine:
    return Engine(
        user_config_path=tmp_path / "user" / "user.json",
        env={},
        layer_cache=LayerCache(use_disk=False),
        registry=load_registry_from_texts({"s.json": json.dumps({"structures": []})}),
    )


def _game_data(tmp_path: Path, name: str = "game") -> Path:
    root = tmp_path / name
    (root / "GameInfo").mkdir(parents=True)
    return root


def _project(tmp_path: Path, name: str = "mod") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def _entities(names: list[str]) -> str:
    lines = ["TXT", f"entityNameCount {len(names)}", *(f'entityName "{n}"' for n in names)]
    return "\n".join(lines) + "\n"


def _manifest_project(tmp_path: Path, listed: list[str], files: list[str]) -> Path:
    root = tmp_path / "mod"
    (root / "GameInfo").mkdir(parents=True)
    (root / "soase.json").write_text("{}", encoding="utf-8")
    (root / "entity.manifest").write_bytes(_entities(listed).encode())
    for file in files:
        (root / "GameInfo" / file).write_text("TXT\n", encoding="utf-8")
    return root


def _settings(project: Path) -> dict:
    return json.loads((project / "soase.json").read_text(encoding="utf-8"))


def test_init_with_a_game_data_root_saves_it_without_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    game = _game_data(tmp_path)

    code = main(
        ["init", "--path", str(project), "--reference-root", str(game), "--no-prompt"],
        _engine(tmp_path),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert str(game) in json.dumps(_settings(project)).replace("\\\\", "\\")
    assert "warning" not in captured.err
    assert "No Reference Root configured" not in captured.out


@pytest.mark.parametrize("kind", ["missing", "not-game-data"])
def test_init_warns_when_the_root_is_unusable_but_still_saves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    project = _project(tmp_path)
    root = tmp_path / "bad"
    if kind == "not-game-data":
        root.mkdir()

    code = main(
        ["init", "--path", str(project), "--reference-root", str(root), "--no-prompt"],
        _engine(tmp_path),
    )

    assert code == 0
    assert "SOASE-C020" in capsys.readouterr().err
    assert "referenceRoots" in _settings(project)


def test_init_without_a_root_or_default_explains_how_to_add_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)

    code = main(["init", "--path", str(project), "--no-prompt"], _engine(tmp_path))

    out = capsys.readouterr().out
    assert code == 0
    assert (project / "soase.json").is_file()
    assert "No Reference Root configured" in out
    assert "set-reference-root" in out
    assert "referenceRoots" not in _settings(project)


def test_init_without_a_root_reports_the_user_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = _engine(tmp_path)
    game = _game_data(tmp_path)
    assert main(["config", "set-reference-root", str(game), "--user"], engine) == 0
    capsys.readouterr()
    project = _project(tmp_path)

    code = main(["init", "--path", str(project), "--no-prompt"], engine)

    out = capsys.readouterr().out
    assert code == 0
    assert "user-level default" in out
    assert str(game) in out
    assert "No Reference Root configured" not in out
    assert "referenceRoots" not in _settings(project)


def test_init_rejects_an_unknown_game_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)

    code = main(
        ["init", "--path", str(project), "--game-version", "nope", "--no-prompt"],
        _engine(tmp_path),
    )

    assert code == 1
    assert "unknown game version" in capsys.readouterr().err
    assert not (project / "soase.json").exists()


def test_init_and_config_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    engine = _engine(tmp_path)
    project = _project(tmp_path)
    assert main(["init", "--path", str(project), "--no-prompt"], engine) == 0
    capsys.readouterr()

    assert main(["config", "show", "--path", str(project)], engine) == 0

    assert "Settings:" in capsys.readouterr().out


def test_set_reference_root_warns_for_a_missing_directory_but_saves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["config", "set-reference-root", "missing-dir", "--path", str(tmp_path)],
        _engine(tmp_path),
    )

    assert code == 0
    assert "SOASE-C020" in capsys.readouterr().err
    assert "missing-dir" in (tmp_path / "soase.json").read_text(encoding="utf-8")


def test_set_reference_root_warns_when_the_directory_is_not_game_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    code = main(
        ["config", "set-reference-root", str(plain), "--path", str(tmp_path)],
        _engine(tmp_path),
    )

    assert code == 0
    assert "SOASE-C020" in capsys.readouterr().err


def test_set_reference_root_accepts_game_data_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    game = _game_data(tmp_path)

    code = main(
        ["config", "set-reference-root", str(game), "--path", str(tmp_path)],
        _engine(tmp_path),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert "Saved" in captured.out


def test_set_reference_root_user_writes_the_user_file_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = _engine(tmp_path)
    game = _game_data(tmp_path)
    project = _project(tmp_path)

    code = main(
        ["config", "set-reference-root", str(game), "--user", "--path", str(project)],
        engine,
    )

    assert code == 0
    assert "Saved" in capsys.readouterr().out
    user_file = tmp_path / "user" / "user.json"
    assert "defaultReferenceRoots" in user_file.read_text(encoding="utf-8")
    assert not (project / "soase.json").exists()


def test_set_reference_root_rejects_an_unknown_game_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["config", "set-reference-root", "x", "--game-version", "nope", "--path", str(tmp_path)],
        _engine(tmp_path),
    )

    assert code == 1
    assert "unknown game version" in capsys.readouterr().err


def test_sync_is_a_dry_run_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _manifest_project(tmp_path, [], ["ship.entity"])
    before = (root / "entity.manifest").read_bytes()

    code = main(["manifest", "sync", "--path", str(root)], _engine(tmp_path))

    out = capsys.readouterr().out
    assert code == 0
    assert "ship.entity" in out
    assert "Dry run" in out
    assert (root / "entity.manifest").read_bytes() == before
    assert not (root / "entity.manifest.old").exists()


def test_sync_write_saves_a_backup_of_the_original(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, [], ["ship.entity"])
    before = (root / "entity.manifest").read_bytes()

    code = main(["manifest", "sync", "--path", str(root), "--write"], _engine(tmp_path))

    assert code == 0
    assert "backup" in capsys.readouterr().out
    assert b"ship.entity" in (root / "entity.manifest").read_bytes()
    assert (root / "entity.manifest.old").read_bytes() == before


def test_sync_reports_when_manifests_are_in_sync(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, ["ship.entity"], ["ship.entity"])

    code = main(["manifest", "sync", "--path", str(root)], _engine(tmp_path))

    assert code == 0
    assert "in sync" in capsys.readouterr().out


def test_sync_keeps_stale_entries_without_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, ["ship.entity", "ghost.entity"], ["ship.entity"])

    code = main(["manifest", "sync", "--path", str(root), "--write"], _engine(tmp_path))

    assert code == 0
    assert b"ghost.entity" in (root / "entity.manifest").read_bytes()
    assert "Entries" not in capsys.readouterr().out


def test_remove_stale_lists_entries_in_a_dry_run_and_removes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, ["ship.entity", "ghost.entity"], ["ship.entity"])
    before = (root / "entity.manifest").read_bytes()

    code = main(["manifest", "sync", "--path", str(root), "--remove-stale"], _engine(tmp_path))

    out = capsys.readouterr().out
    assert code == 0
    assert "Entries to remove:" in out
    assert "entity.manifest: ghost.entity" in out
    assert (root / "entity.manifest").read_bytes() == before


def test_remove_stale_with_write_lists_removes_and_backs_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, ["ship.entity", "ghost.entity"], ["ship.entity"])
    before = (root / "entity.manifest").read_bytes()

    code = main(
        ["manifest", "sync", "--path", str(root), "--remove-stale", "--write"],
        _engine(tmp_path),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Entries removed:" in out
    assert "entity.manifest: ghost.entity" in out
    assert out.index("Entries removed:") < out.index("Wrote")
    assert b"ghost.entity" not in (root / "entity.manifest").read_bytes()
    assert b"ship.entity" in (root / "entity.manifest").read_bytes()
    assert (root / "entity.manifest.old").read_bytes() == before


def test_sync_prints_advisories_for_lower_layer_manifests_and_leaves_them_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "base"
    (base / "GameInfo").mkdir(parents=True)
    (base / "entity.manifest").write_bytes(_entities([]).encode())
    root = tmp_path / "mod"
    (root / "GameInfo").mkdir(parents=True)
    (root / "soase.json").write_text(json.dumps({"layers": [str(base)]}), encoding="utf-8")
    (root / "GameInfo" / "extra.entity").write_text("TXT\n", encoding="utf-8")
    before = (base / "entity.manifest").read_bytes()

    code = main(["manifest", "sync", "--path", str(root), "--write"], _engine(tmp_path))

    out = capsys.readouterr().out
    assert code == 0
    assert "Layer base owns entity.manifest" in out
    assert "extra.entity" in out
    assert (base / "entity.manifest").read_bytes() == before
    assert not (base / "entity.manifest.old").exists()


def test_check_exits_nonzero_for_an_unlisted_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _manifest_project(tmp_path, [], ["ship.entity"])
    engine = _engine(tmp_path)

    assert main(["manifest", "check", "--path", str(root)], engine) == 1
    assert "error" in capsys.readouterr().out

    main(["manifest", "sync", "--path", str(root), "--write"], engine)
    capsys.readouterr()
    assert main(["manifest", "check", "--path", str(root)], engine) == 0


def test_versions_marks_only_rebellion_198_as_audited(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(["versions"], _engine(tmp_path))

    lines = capsys.readouterr().out.splitlines()
    audited = [line for line in lines if line.endswith("(audited)")]
    best_effort = [line for line in lines if line.endswith("(unaudited, best-effort)")]
    assert code == 0
    assert len(audited) == 1 and "rebellion-1.98" in audited[0]
    assert len(best_effort) == 6
    assert "Unverified gate tokens:" in lines


def test_an_unknown_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["nope"])

    assert raised.value.code == 2
