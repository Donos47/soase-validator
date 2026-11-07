"""Unit tests for Layer chain resolution."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from soase_validator.engine.chain import Chain, looks_like_game_data, resolve_chain
from soase_validator.engine.config import ManifestPrefs, ResolvedSettings
from soase_validator.engine.diagnostics import C010, C020
from soase_validator.engine.primitives import NumericPrefs
from soase_validator.engine.versions import DEFAULT_REBELLION, GameVersion


def _settings(
    layers: tuple[str, ...] = (),
    mod_roots: tuple[Path, ...] = (),
    reference_root: Path | None = None,
    aliases: dict[str, Path] | None = None,
) -> ResolvedSettings:
    roots = {DEFAULT_REBELLION: reference_root} if reference_root else {}
    return ResolvedSettings(
        game_version=DEFAULT_REBELLION,
        reference_roots=roots,
        mod_roots=mod_roots,
        layer_specs=layers,
        aliases=aliases or {},
        disabled_codes=frozenset(),
        numeric=NumericPrefs(),
        manifest=ManifestPrefs(),
        report_overrides=False,
        suppress_limited_notice=False,
        project_file=None,
        sources={},
        problems=(),
    )


def _game(root: Path) -> Path:
    (root / "GameInfo").mkdir(parents=True)
    return root


def _mod(root: Path, extends: list[str] | None = None) -> Path:
    root.mkdir(parents=True)
    if extends is not None:
        (root / "soase.json").write_text(json.dumps({"extends": extends}), encoding="utf-8")
    return root


def _names(chain: Chain) -> list[str]:
    return [layer.name for layer in chain.layers]


def test_game_mods_and_project_order(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    parent = _mod(tmp_path / "parent")
    project = _mod(tmp_path / "project")
    chain = resolve_chain(
        _settings((str(parent),), (project,), game),
    )
    assert _names(chain) == ["game", "parent", "project"]
    assert [layer.kind for layer in chain.layers] == ["game", "mod", "project"]
    assert chain.complete
    assert chain.problems == ()


def test_listed_project_keeps_its_position(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    project = _mod(tmp_path / "project")
    other = _mod(tmp_path / "other")
    chain = resolve_chain(_settings((str(project), str(other)), (project,), game))
    assert _names(chain) == ["game", "project", "other"]
    assert chain.layers[1].kind == "project"


def test_extends_spliced_depth_first_below_layer(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    base = _mod(tmp_path / "base")
    _mod(tmp_path / "mid", [str(base)])
    top = _mod(tmp_path / "top", ["../mid"])
    chain = resolve_chain(_settings((str(top),), (), game))
    assert _names(chain) == ["game", "base", "mid", "top"]


def test_duplicate_keeps_lowest_position(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    shared = _mod(tmp_path / "shared")
    a = _mod(tmp_path / "a", [str(shared)])
    b = _mod(tmp_path / "b")
    chain = resolve_chain(_settings((str(a), str(b), str(shared)), (), game))
    assert _names(chain) == ["game", "shared", "a", "b"]


def test_extends_cycle_is_reported_once(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    a = tmp_path / "a"
    b = tmp_path / "b"
    _mod(a, [str(b)])
    _mod(b, [str(a)])
    chain = resolve_chain(_settings((str(a),), (), game))
    cycles = [p for p in chain.problems if p.code == C010]
    assert len(cycles) == 1
    assert str(a) in cycles[0].message and str(b) in cycles[0].message
    assert set(_names(chain)) == {"game", "a", "b"}


def test_alias_expands_and_names_layer(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    shared = _mod(tmp_path / "somewhere" / "e4x")
    chain = resolve_chain(_settings(("@e4x",), (), game, {"e4x": shared}))
    assert _names(chain) == ["game", "@e4x"]
    assert chain.layers[1].path == shared
    assert chain.complete


def test_undefined_alias_is_missing_and_incomplete(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    chain = resolve_chain(_settings(("@nope",), (), game))
    assert chain.layers[-1].status == "missing"
    assert not chain.complete
    assert any(p.code == C020 and "@nope" in p.message for p in chain.problems)


def test_missing_layer_warns_once_and_chain_continues(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    gone = tmp_path / "gone"
    chain = resolve_chain(_settings((str(gone),), (), game))
    assert [layer.status for layer in chain.layers] == ["ok", "missing"]
    warnings = [p for p in chain.problems if p.code == C020]
    assert len(warnings) == 1 and str(gone) in warnings[0].message
    assert not chain.complete


def test_game_root_without_game_data_is_unusable(tmp_path: Path) -> None:
    empty = tmp_path / "game"
    empty.mkdir()
    (empty / "notes").mkdir()
    chain = resolve_chain(_settings((), (), empty))
    assert chain.layers[0].kind == "game"
    assert chain.layers[0].status == "unusable"
    assert not chain.complete
    assert [p.code for p in chain.problems] == [C020]


def test_no_game_layer_with_ok_mods_is_complete(tmp_path: Path) -> None:
    parent = _mod(tmp_path / "parent")
    project = _mod(tmp_path / "project")
    chain = resolve_chain(_settings((str(parent),), (project,)))
    assert _names(chain) == ["parent", "project"]
    assert all(layer.kind != "game" for layer in chain.layers)
    assert chain.complete
    assert chain.problems == ()


def test_no_layers_at_all_is_complete() -> None:
    chain = resolve_chain(_settings())
    assert chain.layers == ()
    assert chain.complete
    assert chain.problems == ()


def test_project_only_is_complete(tmp_path: Path) -> None:
    project = _mod(tmp_path / "project")
    chain = resolve_chain(_settings((), (project,)))
    assert _names(chain) == ["project"]
    assert chain.complete


def test_missing_declared_layer_without_game_layer_is_incomplete(tmp_path: Path) -> None:
    project = _mod(tmp_path / "project")
    chain = resolve_chain(_settings((str(tmp_path / "gone"),), (project,)))
    assert [layer.status for layer in chain.layers] == ["missing", "ok"]
    assert not chain.complete


def test_missing_game_layer_is_incomplete(tmp_path: Path) -> None:
    chain = resolve_chain(_settings((), (), tmp_path / "absent"))
    assert chain.layers[0].kind == "game"
    assert chain.layers[0].status == "missing"
    assert not chain.complete


def test_usable_game_layer_with_mods_is_complete(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    parent = _mod(tmp_path / "parent")
    project = _mod(tmp_path / "project")
    chain = resolve_chain(_settings((str(parent),), (project,), game))
    assert [layer.status for layer in chain.layers] == ["ok", "ok", "ok"]
    assert chain.complete


def test_game_data_marker_is_case_insensitive(tmp_path: Path) -> None:
    game = tmp_path / "game"
    (game / "TEXTUREANIMATIONS").mkdir(parents=True)
    assert looks_like_game_data(game)
    assert not looks_like_game_data(tmp_path / "absent")
    other = tmp_path / "other"
    (other / "Entity").mkdir(parents=True)
    assert not looks_like_game_data(other)


def test_reference_root_of_other_version_is_ignored(tmp_path: Path) -> None:
    other = _game(tmp_path / "vanilla")
    settings = replace(_settings(), reference_roots={GameVersion.VANILLA: other})
    assert resolve_chain(settings).layers == ()


def test_malformed_extends_is_reported(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "soase.json").write_text('{"extends": "x"}', encoding="utf-8")
    chain = resolve_chain(_settings((str(bad),), (), game))
    assert _names(chain) == ["game", "bad"]
    assert any(p.code == C020 and "extends" in p.message for p in chain.problems)


def test_enabled_mods_file_is_ignored(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    (game / "EnabledMods.txt").write_text("1\nother\n", encoding="utf-8")
    chain = resolve_chain(_settings((), (), game))
    assert _names(chain) == ["game"]
