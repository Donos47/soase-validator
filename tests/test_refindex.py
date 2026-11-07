"""Unit tests for the per-Layer file index and file-reference resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from soase_validator.engine.chain import GAME_DATA_DIRECTORIES, Layer
from soase_validator.engine.refindex import (
    InMemoryFileSystem,
    RealFileSystem,
    RefKind,
    build_layer_index,
    compute_signature,
    file_reference_keys,
    find_file,
    is_absolute_reference,
    update_file,
)

ROOT = Path("/layer")


def _layer(path: Path = ROOT) -> Layer:
    return Layer("layer", path, "mod", "ok")


def _fs(*relpaths: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    for i, rel in enumerate(relpaths):
        fs.add_file(ROOT / rel, size=i + 1, mtime_ns=i + 10)
    return fs


def test_scan_covers_game_data_directories_and_root_files() -> None:
    fs = _fs(
        "Mesh/Ship.MESH",
        "Sound/Sub/Boom.ogg",
        "entity.manifest",
        "Notes/readme.txt",
        "Mesh/.hidden/x.MESH",
        ".git/Mesh/y.MESH",
        ".hidden/Mesh/z.MESH",
        "Mesh/.svn/w.MESH",
    )
    index = build_layer_index(_layer(), fs)
    assert set(index.files) == {"mesh/ship.mesh", "sound/sub/boom.ogg", "entity.manifest"}


@pytest.mark.parametrize("directory", GAME_DATA_DIRECTORIES)
def test_scan_covers_every_listed_directory(directory: str) -> None:
    index = build_layer_index(_layer(), _fs(f"{directory}/x.bin", "Other/x.bin"))
    assert set(index.files) == {f"{directory.casefold()}/x.bin"}


def test_scan_covers_the_localizations_layout() -> None:
    index = build_layer_index(_layer(), _fs("Localizations/en/Sound/Boom.ogg"))
    assert set(index.files) == {"localizations/en/sound/boom.ogg"}


def test_directory_list_has_current_and_legacy_names() -> None:
    assert len(set(GAME_DATA_DIRECTORIES)) == len(GAME_DATA_DIRECTORIES)
    assert {"Textures", "Localizations", "Galaxy Forge", "Particle Forge"} <= set(
        GAME_DATA_DIRECTORIES
    )
    assert {"Sound", "String", "Font"} <= set(GAME_DATA_DIRECTORIES)


def test_game_data_directory_names_match_case_insensitively() -> None:
    index = build_layer_index(_layer(), _fs("MESH/Ship.MESH"))
    assert set(index.files) == {"mesh/ship.mesh"}


def test_signature_depends_on_path_size_and_mtime_only() -> None:
    base = {"a": (1, 2), "b": (3, 4)}
    assert compute_signature(base) == compute_signature({"b": (3, 4), "a": (1, 2)})
    assert compute_signature(base) != compute_signature({"a": (1, 2), "b": (3, 5)})
    assert compute_signature(base) != compute_signature({"a": (1, 2), "b": (4, 4)})
    assert compute_signature(base) != compute_signature({"a": (1, 2), "c": (3, 4)})


def test_update_file_matches_full_rebuild() -> None:
    fs = _fs("Mesh/A.MESH", "Particle/B.particle")
    index = build_layer_index(_layer(), fs)

    fs.add_file(ROOT / "Mesh/A.MESH", size=99, mtime_ns=5)
    fs.add_file(ROOT / "Sound/C.ogg", size=7, mtime_ns=6)
    fs.remove_file(ROOT / "Particle/B.particle")
    for path in ("Mesh/A.MESH", "Sound/C.ogg", "Particle/B.particle"):
        index = update_file(index, ROOT / path, fs)

    rebuilt = build_layer_index(_layer(), fs)
    assert index.files == rebuilt.files
    assert index.stats == rebuilt.stats
    assert index.signature == rebuilt.signature


def test_update_file_ignores_paths_outside_scope() -> None:
    fs = _fs("Mesh/A.MESH")
    index = build_layer_index(_layer(), fs)
    for path in (ROOT / "Notes/x.txt", ROOT / "Mesh/.git/x.MESH", Path("/other/Mesh/x.MESH")):
        fs.add_file(path, 1, 1)
        assert update_file(index, path, fs) is index


@pytest.mark.parametrize(
    ("kind", "name", "file_extension", "relpaths"),
    [
        (
            "SoundFile",
            "Advent 1.ogg",
            ".sounddata",
            ("localizations/en/sound/advent 1.ogg", "sound/advent 1.ogg"),
        ),
        ("Mesh", "Ship", ".entity", ("mesh/ship.mesh",)),
        ("Mesh", "Ship.MESH", ".particle", ("mesh/ship.mesh",)),
        ("Mesh", "Ship", ".particle", ("mesh/ship.mesh",)),
        ("Mesh", "Ship.MESH", ".entity", ("mesh/ship.mesh.mesh",)),
        ("Particle", "Ability_Fx", ".entity", ("particle/ability_fx.particle",)),
        ("Texture", "Icon", ".brushes", ("textures/icon.dds", "textures/icon.tga")),
        ("Texture", "Icon.TGA", ".particle", ("textures/icon.tga",)),
        ("Texture", "Icon.png", ".particle", ("textures/icon.png",)),
    ],
)
def test_file_reference_keys(
    kind: str, name: str, file_extension: str, relpaths: tuple[str, ...]
) -> None:
    assert file_reference_keys(kind, name, file_extension) == relpaths


@pytest.mark.parametrize("kind", ["Brush", "Entity", "Unknown"])
def test_other_kinds_are_not_file_references(kind: str) -> None:
    assert file_reference_keys(kind, "Name") is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (r"C:\Users\author\Textures\Flare.tga", True),
        ("c:Flare", True),
        ("Textures/Flare", True),
        (r"dir\Flare", True),
        ("Flare", False),
        ("", False),
        ("a", False),
    ],
)
def test_is_absolute_reference(name: str, expected: bool) -> None:
    assert is_absolute_reference(name) is expected


def test_texture_resolves_either_extension_or_exact_name() -> None:
    index = build_layer_index(
        _layer(), _fs("Textures/Flare.TGA", "Textures/Icon.dds", "Textures/Both.dds")
    )
    assert find_file([index], "Texture", "flare") == ROOT / "Textures/Flare.TGA"
    assert find_file([index], "Texture", "ICON") == ROOT / "Textures/Icon.dds"
    assert find_file([index], "Texture", "Flare.tga") == ROOT / "Textures/Flare.TGA"
    assert find_file([index], "Texture", "Icon.dds") == ROOT / "Textures/Icon.dds"
    assert find_file([index], "Texture", "Flare.dds") is None
    assert find_file([index], "Texture", "Missing") is None


def test_mesh_extension_is_accepted_only_for_particle_files() -> None:
    index = build_layer_index(_layer(), _fs("Mesh/Ship.MESH"))
    assert find_file([index], "Mesh", "Ship.mesh", ".particle") == ROOT / "Mesh/Ship.MESH"
    assert find_file([index], "Mesh", "Ship", ".particle") == ROOT / "Mesh/Ship.MESH"
    assert find_file([index], "Mesh", "Ship", ".entity") == ROOT / "Mesh/Ship.MESH"
    assert find_file([index], "Mesh", "Ship.mesh", ".entity") is None
    assert find_file([index], "Mesh", "Ship.mesh") is None


def test_find_file_is_case_insensitive_and_highest_layer_wins() -> None:
    low_root = Path("/low")
    low_fs = InMemoryFileSystem()
    low_fs.add_file(low_root / "Mesh/Ship.MESH")
    high_fs = _fs("Mesh/ship.mesh", "Sound/Boom.ogg")
    low = build_layer_index(_layer(low_root), low_fs)
    high = build_layer_index(_layer(), high_fs)

    assert find_file([high, low], RefKind.MESH, "SHIP") == ROOT / "Mesh/ship.mesh"
    assert find_file([low], "Mesh", "Ship") == low_root / "Mesh/Ship.MESH"
    assert find_file([high, low], RefKind.MESH, "Missing") is None
    assert find_file([high, low], RefKind.SOUND_FILE, "Boom.ogg") == ROOT / "Sound/Boom.ogg"
    assert find_file([high, low], RefKind.SOUND_FILE, "Boom") == ROOT / "Sound/Boom.ogg"
    assert find_file([high], RefKind.SOUND_FILE, "Boom.wav") is None
    assert find_file([high], RefKind.PARTICLE, "Ship") is None


def test_real_file_system_index(tmp_path: Path) -> None:
    (tmp_path / "Mesh").mkdir()
    (tmp_path / "Mesh" / "Ship.MESH").write_bytes(b"x")
    (tmp_path / ".git" / "Mesh").mkdir(parents=True)
    (tmp_path / ".git" / "Mesh" / "Bad.MESH").write_bytes(b"x")
    (tmp_path / "brush.manifest").write_text("TXT\n")
    index = build_layer_index(_layer(tmp_path), RealFileSystem())
    assert set(index.files) == {"mesh/ship.mesh", "brush.manifest"}

    (tmp_path / "Mesh" / "Ship.MESH").write_bytes(b"xyz")
    updated = update_file(index, tmp_path / "Mesh" / "Ship.MESH")
    assert updated.signature != index.signature
    assert updated.signature == build_layer_index(_layer(tmp_path)).signature


def test_missing_layer_directory_gives_empty_index(tmp_path: Path) -> None:
    index = build_layer_index(_layer(tmp_path / "absent"))
    assert dict(index.files) == {}
