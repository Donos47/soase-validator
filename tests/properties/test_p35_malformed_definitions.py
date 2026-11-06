# Feature: soase-validator, Property 35: Malformed Definitions do not block loading
"""Property test: malformed Definition input never blocks loading.

**Validates: Requirements 1.3**

Valid generated Definitions are serialized, then malformed material is mixed
in: files that are not JSON, files with a non-object top level, malformed
structures, nodes, element rules and enums, and dangling structure
references. Loading must not raise, every valid structure, element rule and
enum must still load equal to the model, and each problem must yield exactly
one ``SOASE-D001`` warning naming the file and element.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.strategies.definitions import ENUMS_FILE, DefinitionSet, definitions, serialize

from soase_validator.engine.registry import load_registry_from_texts

_INVALID_JSON = st.sampled_from(["{", "not json", '{"structures": [', "", "{'a': 1}"])
_NON_OBJECT = st.sampled_from(["[]", "42", '"text"', "null", "true"])


def _bad_elements_file() -> tuple[str, set[tuple[str, str]]]:
    """Build a structure file full of malformed elements.

    Returns:
        The JSON text and the (file, element) warnings it must produce.
    """
    name = "bad_elements.json"
    doc = {
        "structures": [
            {"children": []},
            {"name": "BadChild", "children": [{"node": "field"}, {"node": "bogus", "name": "x"}]},
            {"name": "BadType", "children": [{"node": "field", "name": "y", "type": 5}]},
            "not an object",
        ],
        "element_rules": [{"name": "BadRule", "limit": "many"}],
    }
    expected = {
        (name, "structures"),
        (name, "BadChild"),
        (name, "BadChild.x"),
        (name, "BadType.y"),
        (name, "BadRule"),
    }
    # "not an object" has no name, so it is reported under the list key.
    return json.dumps(doc), expected


def _dangling_file() -> tuple[str, set[tuple[str, str]]]:
    """Build a structure file with dangling structure references.

    Returns:
        The JSON text and the (file, element) warnings it must produce.
    """
    name = "dangling.json"
    doc = {
        "structures": [
            {
                "name": "BadDangling",
                "children": [
                    {"node": "structure_reference", "name": "ref", "structure": "MissingOne"},
                    {
                        "node": "condition_reference",
                        "name": "cond",
                        "selector": "kind",
                        "cases": {"a": "MissingTwo"},
                    },
                ],
            }
        ]
    }
    return json.dumps(doc), {(name, "BadDangling.ref"), (name, "BadDangling.cond")}


@given(
    defs=definitions(),
    invalid_json=st.none() | _INVALID_JSON,
    non_object=st.none() | _NON_OBJECT,
    with_bad_elements=st.booleans(),
    with_dangling=st.booleans(),
    with_bad_enum=st.booleans(),
)
@settings(max_examples=100, deadline=None)
def test_malformed_definitions_do_not_block_loading(
    defs: DefinitionSet,
    invalid_json: str | None,
    non_object: str | None,
    with_bad_elements: bool,
    with_dangling: bool,
    with_bad_enum: bool,
) -> None:
    """Valid Definitions load intact and each problem yields one SOASE-D001.

    Args:
        defs: Valid generated Definitions.
        invalid_json: Optional text for a file that is not valid JSON.
        non_object: Optional text for a file whose top level is not an object.
        with_bad_elements: Whether to add a file of malformed elements.
        with_dangling: Whether to add a file with dangling references.
        with_bad_enum: Whether to add a malformed enum to ``enums.json``.

    Returns:
        None.

    Raises:
        AssertionError: If loading raises or the outcome differs.
    """
    files = serialize(defs)
    expected: set[tuple[str, str]] = set()

    if invalid_json is not None:
        files["broken.json"] = invalid_json
        expected.add(("broken.json", "broken.json"))
    if non_object is not None:
        files["toplevel.json"] = non_object
        expected.add(("toplevel.json", "toplevel.json"))
    if with_bad_elements:
        text, found = _bad_elements_file()
        files["bad_elements.json"] = text
        expected |= found
    if with_dangling:
        text, found = _dangling_file()
        files["dangling.json"] = text
        expected |= found
    if with_bad_enum:
        doc = json.loads(files[ENUMS_FILE])
        doc["enums"].append({"name": "BadEnum", "values": [5]})
        files[ENUMS_FILE] = json.dumps(doc)
        expected.add((ENUMS_FILE, "BadEnum"))

    registry = load_registry_from_texts(files)

    for struct in defs.structures:
        assert registry.structure(struct.name) == struct
        if struct.extension:
            assert registry.structure_for_extension(struct.extension) == struct
    for rule in defs.element_rules:
        assert registry.element_rule(rule.name) == rule
    for enum in defs.enums:
        assert registry.enum(enum.name) == enum

    assert all(w.code == "SOASE-D001" for w in registry.warnings)
    reported = [(w.file, w.element) for w in registry.warnings]
    assert set(reported) == expected
