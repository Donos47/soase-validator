"""Parser tests for the verified format facts in design.md (synthetic snippets)."""

from __future__ import annotations

import inspect
from pathlib import Path

from soase_validator.engine import parser
from soase_validator.engine.parser import (
    ListValue,
    NumberValue,
    StringValue,
    parse,
    read_text_file,
)


def test_txt_header_galaxy_style() -> None:
    p = parse("TXT\nversionNumber 193\nstarCount 0\n")
    assert p.header == "TXT" and p.complete and not p.diagnostics
    assert p.nodes[0].value == NumberValue("193", 193)


def test_txt2_header_entity_style() -> None:
    p = parse('TXT2\nSinsArchiveVersion 194\nentityType "Frigate"\n')
    assert p.header == "TXT2" and not p.diagnostics
    assert p.nodes[1].value == StringValue("Frigate")


def test_colon_key_with_six_place_decimal() -> None:
    p = parse("TXT\nLevel:0 0.000000\n")
    node = p.nodes[0]
    assert node.key == "Level:0" and not p.diagnostics
    assert isinstance(node.value, NumberValue)
    assert node.value.raw == "0.000000" and node.value.value == 0.0


def test_bracket_position_list() -> None:
    p = parse("TXT\npos [ 234 , 219 ]\n")
    value = p.nodes[0].value
    assert isinstance(value, ListValue) and not p.diagnostics
    assert [i.value for i in value.items] == [234, 219]


def test_empty_string_values() -> None:
    p = parse('TXT\na ""\nb ""\n')
    assert not p.diagnostics
    assert [n.value for n in p.nodes] == [StringValue(""), StringValue("")]


def test_zero_counts_followed_by_no_blocks() -> None:
    text = "TXT\nstarCount 0\nplanetCount 0\ntriggerCount 0\nNumResearchPrerequisites 0\nz 1\n"
    p = parse(text)
    assert not p.diagnostics
    assert [n.key for n in p.nodes][-1] == "z"
    assert all(n.value.value == 0 for n in p.nodes[:4])


def test_space_indented_blocks_accepted_without_diagnostic() -> None:
    p = parse("TXT\nblk\n    a 1\n    b 2\nc 3\n")
    assert not p.diagnostics
    assert [c.key for c in p.nodes[0].children] == ["a", "b"]


def test_unterminated_quote_reports_p003() -> None:
    p = parse('TXT\nname "open\n')
    assert [d.code for d in p.diagnostics] == ["SOASE-P003"]
    assert p.nodes[0].value == StringValue("open", terminated=False)


def test_parse_is_extension_agnostic(tmp_path: Path) -> None:
    assert "ext" not in inspect.signature(parse).parameters
    for name in ("a.entity", "a.unknownext", "a.manifest", "noext"):
        f = tmp_path / name
        f.write_text("TXT\nk 1\n", encoding="utf-8")
        p = parse(read_text_file(f))
        assert p.header == "TXT" and not p.diagnostics
        assert p.nodes[0].key == "k"
    assert "suffix" not in inspect.getsource(parser)
