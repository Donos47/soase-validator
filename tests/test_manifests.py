"""Unit tests for manifest rules, parsing and formatting."""

from __future__ import annotations

import pytest

from soase_validator.engine.manifests import (
    build_manifest,
    format_manifest,
    listed_name,
    load_manifest_rules,
    parse_manifest,
    rule_for,
)

CRLF = "\r\n"


def _rule(name: str):
    rule = rule_for(name)
    assert rule is not None
    return rule


def test_rules_cover_all_manifest_types() -> None:
    rules = load_manifest_rules()
    assert set(rules) == {
        "entity.manifest",
        "brush.manifest",
        "galaxy.manifest",
        "playerpictures.manifest",
        "playerthemes.manifest",
        "skybox.manifest",
    }


def test_rule_lookup_ignores_case_and_directories() -> None:
    assert _rule("PlayerPictures.MANIFEST").count_key == "fileCount"
    assert _rule("some/dir/skybox.manifest").name_key == "meshFileName"
    assert rule_for("other.manifest") is None


def test_rule_fields() -> None:
    entity = _rule("entity.manifest")
    assert (entity.count_key, entity.name_key) == ("entityNameCount", "entityName")
    assert entity.directory == "GameInfo"
    assert entity.extensions == (".entity",)
    for name in ("brush.manifest", "playerPictures.manifest", "playerThemes.manifest"):
        assert _rule(name).directory == "Window"
    assert _rule("skybox.manifest").identified_by == "skyboxbackdropdata.meshName"


def test_parse_real_shaped_crlf_manifest() -> None:
    rule = _rule("entity.manifest")
    text = CRLF.join(
        ["TXT", "entityNameCount 2", 'entityName "A.entity"', 'entityName "B.entity"\t', ""]
    )
    data = parse_manifest(text, rule)
    assert data.header == "TXT"
    assert data.eol == CRLF
    assert data.final_newline
    assert data.count == 2
    assert data.count_line == 1
    assert data.names == ("A.entity", "B.entity")
    assert data.entries[1].line == 3
    assert not data.problems
    assert format_manifest(data, rule) == text


def test_parse_lf_txt2_without_final_newline() -> None:
    rule = _rule("brush.manifest")
    text = 'TXT2\nbrushFileCount 1\nbrushFile "X.brushes"'
    data = parse_manifest(text, rule)
    assert (data.header, data.eol, data.final_newline) == ("TXT2", "\n", False)
    assert format_manifest(data, rule) == text


def test_names_match_ignoring_case() -> None:
    rule = _rule("skybox.manifest")
    text = CRLF.join(["TXT", "meshFileCount 1", 'meshFileName "SkyboxBackdrop2.MESH"', ""])
    data = parse_manifest(text, rule)
    assert data.lists("skyboxbackdrop2.mesh")
    assert not data.lists("SkyboxBackdrop3.MESH")


def test_galaxy_names_have_no_extension() -> None:
    rule = _rule("galaxy.manifest")
    assert listed_name(rule, "Agamemnon's Bounty.galaxy") == "Agamemnon's Bounty"
    assert listed_name(_rule("entity.manifest"), "A.entity") == "A.entity"


def test_malformed_lines_are_reported_not_raised() -> None:
    rule = _rule("galaxy.manifest")
    data = parse_manifest('TXT\nfileName "A"\nfileCount x\n', rule)
    lines = {problem.line for problem in data.problems}
    assert 2 in lines
    assert data.count is None
    assert data.names == ("A",)


def test_missing_header_and_empty_text() -> None:
    rule = _rule("galaxy.manifest")
    assert parse_manifest("fileCount 0\n", rule).header is None
    empty = parse_manifest("", rule)
    assert empty.entries == ()
    assert empty.problems


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_build_manifest_round_trips(eol: str) -> None:
    rule = _rule("playerThemes.manifest")
    built = build_manifest(rule, ["A.playerThemes", "B.playerThemes"], header="TXT2", eol=eol)
    text = format_manifest(built, rule)
    assert text == eol.join(
        [
            "TXT2",
            "fileCount 2",
            'fileName "A.playerThemes"',
            'fileName "B.playerThemes"',
            "",
        ]
    )
    reparsed = parse_manifest(text, rule)
    assert reparsed.names == built.names
    assert reparsed.count == 2
    assert format_manifest(reparsed, rule) == text


def test_build_manifest_rejects_unknown_header() -> None:
    with pytest.raises(ValueError, match="header"):
        build_manifest(_rule("entity.manifest"), [], header="TXT3")
