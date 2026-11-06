from hypothesis import given, settings
from hypothesis import strategies as st

from sose_validator.engine.versions import (
    GATE_TOKENS,
    GameVersion,
    VersionData,
    audit_status,
    capabilities,
    gate_allows,
    parse_game_version,
    parse_version_data,
)

V = GameVersion


def test_bare_rebellion_is_196():
    assert parse_game_version("Rebellion") is V.REBELLION_196
    assert parse_game_version("Rebellion 1.96") is V.REBELLION_196
    assert parse_game_version("nope") is None


def test_empty_gate_allows_all():
    for v in V:
        assert gate_allows(None, v)
        assert gate_allows("  ", v)


def test_token_semantics():
    assert gate_allows("EntrenchmentOnly", V.ENTRENCHMENT)
    assert not gate_allows("EntrenchmentOnly", V.DIPLOMACY)
    assert gate_allows("Rebellion", V.REBELLION_196)
    assert not gate_allows("Rebellion", V.DIPLOMACY)
    assert gate_allows("NotRebellion", V.VANILLA)
    assert not gate_allows("NotRebellion", V.REBELLION_185)
    assert not gate_allows("Rebellion193", V.REBELLION_185)
    assert gate_allows("DiplomacyOnly, Rebellion194", V.REBELLION_196)
    assert gate_allows("DiplomacyOnly Rebellion", V.DIPLOMACY)


def test_overrides_apply_to_196_only():
    data = parse_version_data({"overrides": {"rebellion-1.96": {"remove": ["Rebellion194"]}}})
    assert "Rebellion194" not in capabilities(V.REBELLION_196, data)
    assert "Rebellion194" in capabilities(V.REBELLION_194, data)


def test_bundled_audit_status():
    assert audit_status(V.REBELLION_196) == "audited"
    assert all(audit_status(v) == "unaudited" for v in V if v is not V.REBELLION_196)
    assert audit_status(V.VANILLA, VersionData()) == "unaudited"


@settings(max_examples=100)
@given(st.lists(st.sampled_from(sorted(GATE_TOKENS)), max_size=5), st.sampled_from([",", " "]))
def test_196_matches_194_without_overrides(tokens, sep):
    gate = sep.join(tokens)
    assert gate_allows(gate, V.REBELLION_196) == gate_allows(gate, V.REBELLION_194)
