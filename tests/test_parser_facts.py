"""Parser tests for the verified format facts in design.md (synthetic snippets)."""

from __future__ import annotations

import inspect
from pathlib import Path

from soase_validator.engine import parser
from soase_validator.engine.model import Span
from soase_validator.engine.parser import (
    HexValue,
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


def test_bare_hex_color_token_is_a_hex_value() -> None:
    p = parse("TXT\ncolor ffffffff\nupper ffFF891D\nzero 0\n")
    assert not p.diagnostics
    assert p.nodes[0].value == HexValue("ffffffff")
    assert p.nodes[1].value == HexValue("ffFF891D")
    assert p.nodes[2].value == NumberValue("0", 0)


def test_all_digit_token_stays_a_number_with_raw_text() -> None:
    value = parse("TXT\ncolor 00000000\n").nodes[0].value
    assert isinstance(value, NumberValue) and value.raw == "00000000"


def test_space_separated_list_records_separator() -> None:
    p = parse("TXT\nPosition [ 0.000000 0.100000 0.000000 ]\npos [ 234 , 219 ]\n")
    assert not p.diagnostics
    first, second = (n.value for n in p.nodes)
    assert isinstance(first, ListValue) and first.separator == " " and len(first.items) == 3
    assert isinstance(second, ListValue) and second.separator == ","


def test_comma_list_without_spaces_after_bracket() -> None:
    value = parse("TXT\narea [9, 99, 999, 99]\n").nodes[0].value
    assert isinstance(value, ListValue) and [i.raw for i in value.items] == ["9", "99", "999", "99"]


def test_keyless_rows_become_children_of_the_header() -> None:
    text = (
        "TXT\nOrientation\n"
        "\t [ 1.000000 0.000000 0.000000 ]\n"
        "\t [ 0.000000 1.000000 0.000000 ]\n"
        "\t [ 0.000000 0.000000 1.000000 ]\n"
        "next 1\n"
    )
    p = parse(text)
    assert not p.diagnostics
    header = p.nodes[0]
    assert header.key == "Orientation" and header.value is None
    assert [c.key for c in header.children] == ["", "", ""]
    assert all(isinstance(c.value, ListValue) and c.value.separator == " " for c in header.children)
    assert p.nodes[1].key == "next"


def test_malformed_lists_are_still_rejected() -> None:
    p = parse("TXT\na [ 1 , 2\nb [ 1 , 2 ]]\nc 1\n")
    assert [d.code for d in p.diagnostics] == ["SOASE-P002", "SOASE-P002"]
    assert [n.key for n in p.nodes] == ["c"]


def test_equals_form_reads_like_plain_quoted_form() -> None:
    # Shape of the 22 `.constants` lines in the Rebellion 1.98 reference files:
    # `key = "value"`, whitespace on both sides of the `=`, quoted value.
    plain = parse('TXT2\nweaponDefName "Alpha"\n')
    equals = parse('TXT2\nweaponDefName = "Alpha"\n')
    assert equals.complete and not equals.diagnostics
    a, b = plain.nodes[0], equals.nodes[0]
    assert (b.key, b.value) == (a.key, a.value) == ("weaponDefName", StringValue("Alpha"))


def test_equals_form_spans_cover_key_and_quoted_value() -> None:
    node = parse('TXT2\n\tkey  =  "v"\n').nodes[0]
    assert node.key_span == Span(1, 1, 1, 4)
    assert node.value_span == Span(1, 9, 1, 12)
    assert node.extent == Span(1, 1, 1, 12)


def test_equals_form_works_for_empty_and_nested_values() -> None:
    p = parse('TXT2\nblock\n\ta = ""\n\tb = "x"\n')
    assert not p.diagnostics
    assert [(c.key, c.value) for c in p.nodes[0].children] == [
        ("a", StringValue("")),
        ("b", StringValue("x")),
    ]


def test_equals_form_unterminated_quote_still_reported() -> None:
    p = parse('TXT2\nk = "oops\n')
    assert [d.code for d in p.diagnostics] == ["SOASE-P003"]
    assert p.nodes[0].value == StringValue("oops", terminated=False)


def test_key_containing_equals_is_skipped() -> None:
    # `key= "v"` (no space before `=`) and any other key holding `=` are
    # not the surveyed shape; 0 keys with `=` occur in the reference files.
    for line in ('k= "v"', 'a=b "v"', "k= 5", "k=", '=k "v"'):
        p = parse(f"TXT2\n{line}\nz 1\n")
        assert [d.code for d in p.diagnostics] == ["SOASE-P002"], line
        assert [n.key for n in p.nodes] == ["z"], line
        assert not p.complete, line


def test_equals_without_quoted_value_is_still_skipped() -> None:
    # Only the surveyed shape is accepted: no unquoted value, no missing
    # space after `=`, no bare `=`.
    for line in ("k = 5", 'k ="v"', "k =", "k = TRUE"):
        p = parse(f"TXT2\n{line}\nz 1\n")
        assert [d.code for d in p.diagnostics] == ["SOASE-P002"], line
        assert [n.key for n in p.nodes] == ["z"], line


def test_text_after_closing_quote_is_skipped_as_p002() -> None:
    # Shapes of the 6 Rebellion 1.98 lines (5 `.str`, 1 `.window`) plus the
    # whitespace separated shapes, all reported by user decision.
    cases = {
        "doubled closing quote": 'Value "text""',
        "letters after the quote": 'fontId "ButtonLabel"new',
        "second string": 'a "x" "y"',
        "equals form with tail": 'k = "v" tail',
    }
    for name, line in cases.items():
        p = parse(f"TXT2\n{line}\nz 1\n")
        assert [d.code for d in p.diagnostics] == ["SOASE-P002"], name
        assert [n.key for n in p.nodes] == ["z"], name
        assert not p.complete, name


def test_trailing_text_p002_span_covers_the_line() -> None:
    d = parse('TXT2\n\ta "x" "y"\n').diagnostics[0]
    assert (d.range.start.line, d.range.start.col) == (1, 1)
    assert (d.range.end.line, d.range.end.col) == (1, 10)


def test_unterminated_quote_stays_p003_not_p002() -> None:
    p = parse('TXT2\na "x" "y\nb "open\n')
    assert [d.code for d in p.diagnostics] == ["SOASE-P002", "SOASE-P003"]


def test_complete_quoted_values_still_parse() -> None:
    p = parse('TXT2\na ""\nb "v"\nc = "v"\nd "v"   \n')
    assert not p.diagnostics and p.complete
    assert [n.key for n in p.nodes] == ["a", "b", "c", "d"]
