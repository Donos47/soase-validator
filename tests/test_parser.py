"""Unit tests for the tolerant parser."""

from __future__ import annotations

from pathlib import Path

from soase_validator.engine.parser import (
    BoolValue,
    ListValue,
    NumberValue,
    StringValue,
    format_tree,
    parse,
    read_text_file,
)


def _codes(text: str, **kw) -> list[str]:
    return [d.code for d in parse(text, **kw).diagnostics]


def test_basic_values_and_positions() -> None:
    p = parse('TXT2\nSinsArchiveVersion 194\nname ""\nflag TRUE\npos [ 234 , 219 ]\nx 0.500000\n')
    assert p.header == "TXT2" and p.complete
    by_key = {n.key: n for n in p.nodes}
    assert by_key["SinsArchiveVersion"].value == NumberValue("194", 194)
    assert by_key["name"].value == StringValue("")
    assert by_key["flag"].value == BoolValue(True)
    assert isinstance(by_key["pos"].value, ListValue)
    assert [i.value for i in by_key["pos"].value.items] == [234, 219]
    assert by_key["x"].value.value == 0.5
    k = by_key["flag"].key_span
    assert (k.line, k.col, k.end_col) == (3, 0, 4)


def test_colon_key_and_mixed_indent_blocks() -> None:
    p = parse("TXT\nstar\n\tLevel:0 0.0\n\tinner\n\t\ta 1\nb 2\nblk\n  c 3\n")
    star = p.nodes[0]
    assert [c.key for c in star.children] == ["Level:0", "inner"]
    assert star.children[1].children[0].key == "a"
    assert [n.key for n in p.nodes] == ["star", "b", "blk"]
    assert p.nodes[2].children[0].key == "c"
    assert star.extent.end_line == 4


def test_missing_header_and_empty_file() -> None:
    p = parse("a 1\n")
    assert [d.code for d in p.diagnostics] == ["SOASE-P001"]
    assert p.diagnostics[0].range.start.line == 0 and p.nodes[0].key == "a"
    assert _codes("") == ["SOASE-P001"]


def test_unterminated_quote_and_skipped_line() -> None:
    p = parse('TXT\na "oops\nb ???\nc 1\n')
    assert _codes('TXT\na "oops\nb ???\nc 1\n') == ["SOASE-P003", "SOASE-P002"]
    assert p.nodes[0].value == StringValue("oops", terminated=False)
    assert [n.key for n in p.nodes] == ["a", "c"] and not p.complete


def test_archive_version_checks() -> None:
    assert _codes("TXT2\nSinsArchiveVersion 999\n", known_archive_versions={194}) == ["SOASE-P004"]
    d = parse("TXT2\nSinsArchiveVersion 1.5\n").diagnostics[0]
    assert d.severity == "error"
    assert _codes("TXT\nSinsArchiveVersion abc\n") == ["SOASE-P002"]
    assert _codes("TXT\nversionNumber 193\n") == []
    assert _codes("TXT2\na 1\n") == []


def test_count_keys_are_ordinary_and_format_roundtrip() -> None:
    text = "TXT2\nstarCount 2\nstar\n\tpos [ 1 , 2 ]\nstar\n\tpos [ 3 , 4 ]\n"
    p = parse(text)
    assert [n.key for n in p.nodes] == ["starCount", "star", "star"]
    assert format_tree(p) == text
    assert format_tree(parse(format_tree(p))) == text


def test_read_text_file_encodings(tmp_path: Path) -> None:
    f = tmp_path / "a.entity"
    f.write_bytes(b"\xef\xbb\xbfTXT\n")
    assert read_text_file(f) == "TXT\n"
    f.write_bytes(b"TXT\n\xe9\n")
    assert read_text_file(f) == "TXT\n\xe9\n"
