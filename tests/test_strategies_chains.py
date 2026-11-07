"""Smoke tests for the chain strategies."""

from __future__ import annotations

from hypothesis import given, settings
from tests.strategies.chains import GenChain, chains

from soase_validator.engine.refindex import build_layer_index


@settings(max_examples=100)
@given(chains())
def test_layers_are_buildable(gen: GenChain) -> None:
    """Every generated Layer indexes to exactly the expected keys."""
    assert gen.chain.layers[-1].kind == "project"
    assert gen.chain.layers[-1].status == "ok"
    for item in gen.layers:
        index = build_layer_index(item.layer, gen.fs)
        assert set(index.files) == item.expected_keys
        if item.layer.status == "missing":
            assert not index.files


@settings(max_examples=100)
@given(chains(complete=True))
def test_complete_chains_have_no_broken_layers(gen: GenChain) -> None:
    """A complete Chain has only ok lower Layers and no problems."""
    assert gen.chain.complete
    assert not gen.chain.problems
    assert all(layer.status == "ok" for layer in gen.chain.layers)


@settings(max_examples=100)
@given(chains(complete=False))
def test_incomplete_chains_have_a_broken_layer(gen: GenChain) -> None:
    """An incomplete Chain has a missing or unusable lower Layer."""
    assert not gen.chain.complete
    assert gen.chain.problems
    assert any(layer.status != "ok" for layer in gen.chain.layers[:-1])
