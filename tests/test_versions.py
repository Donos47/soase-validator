"""Tests for game version gating and archive version helpers."""

from hypothesis import given, settings
from hypothesis import strategies as st

from soase_validator.engine.versions import (
    GATE_TOKENS,
    GameVersion,
    VersionData,
    archive_level,
    audit_status,
    capabilities,
    effective_version,
    gate_allows,
    introduced_in,
    is_newer_than,
    parse_game_version,
    parse_version_data,
)

V = GameVersion


def test_bare_rebellion_is_198():
    assert parse_game_version("Rebellion") is V.REBELLION_198
    assert parse_game_version("Rebellion 1.98") is V.REBELLION_198
    assert parse_game_version("nope") is None


def test_empty_gate_allows_all():
    for v in V:
        assert gate_allows(None, v)
        assert gate_allows("  ", v)


def test_token_semantics():
    assert gate_allows("EntrenchmentOnly", V.ENTRENCHMENT)
    assert not gate_allows("EntrenchmentOnly", V.DIPLOMACY)
    assert gate_allows("Rebellion", V.REBELLION_198)
    assert not gate_allows("Rebellion", V.DIPLOMACY)
    assert gate_allows("NotRebellion", V.VANILLA)
    assert not gate_allows("NotRebellion", V.REBELLION_185)
    assert not gate_allows("Rebellion193", V.REBELLION_185)
    assert gate_allows("DiplomacyOnly, Rebellion194", V.REBELLION_198)
    assert gate_allows("DiplomacyOnly Rebellion", V.DIPLOMACY)


def test_overrides_apply_to_198_only():
    data = parse_version_data({"overrides": {"rebellion-1.98": {"remove": ["Rebellion194"]}}})
    assert "Rebellion194" not in capabilities(V.REBELLION_198, data)
    assert "Rebellion194" in capabilities(V.REBELLION_194, data)


def test_bundled_audit_status():
    assert audit_status(V.REBELLION_198) == "audited"
    assert all(audit_status(v) == "unaudited" for v in V if v is not V.REBELLION_198)
    assert audit_status(V.VANILLA, VersionData()) == "unaudited"


@settings(max_examples=100)
@given(st.lists(st.sampled_from(sorted(GATE_TOKENS)), max_size=5), st.sampled_from([",", " "]))
def test_198_matches_194_without_overrides(tokens, sep):
    gate = sep.join(tokens)
    assert gate_allows(gate, V.REBELLION_198) == gate_allows(gate, V.REBELLION_194)


def test_effective_version_caps_archive_level_at_project():
    # Backwards compatible: an older known label keeps its own level.
    assert effective_version(193, V.REBELLION_198) is V.REBELLION_193
    assert effective_version(185, V.REBELLION_194) is V.REBELLION_185
    assert effective_version(193, V.REBELLION_193) is V.REBELLION_193
    # 1.98 starts from the 194 set: a 194 file in a 1.98 project uses 1.98.
    assert effective_version(194, V.REBELLION_198) is V.REBELLION_198
    assert effective_version(194, V.REBELLION_194) is V.REBELLION_194
    # Newer than the project, unknown or absent: the project level.
    assert effective_version(194, V.REBELLION_193) is V.REBELLION_193
    assert effective_version(185, V.DIPLOMACY) is V.DIPLOMACY
    assert effective_version(999, V.REBELLION_198) is V.REBELLION_198
    assert effective_version(None, V.REBELLION_193) is V.REBELLION_193


def test_archive_levels_match_capability_sets():
    assert archive_level(193) is V.REBELLION_193
    assert archive_level(7) is None
    assert "Rebellion194" in capabilities(archive_level(194))
    assert "Rebellion194" not in capabilities(archive_level(193))
    assert is_newer_than(V.REBELLION_198, V.REBELLION_194)
    assert not is_newer_than(V.REBELLION_194, V.REBELLION_194)


def test_introduced_in_finds_oldest_rebellion_level():
    assert introduced_in("Rebellion194") is V.REBELLION_194
    assert introduced_in("Rebellion193, Rebellion194") is V.REBELLION_193
    assert introduced_in("NotRebellion") is None
