"""Property keys the sanitizer renames for the provider are restored at dispatch at EVERY depth
it renamed them — including models reached through ``$ref`` and ``anyOf``/``oneOf`` branches."""

from tools.schema_sanitizer import sanitize_tool_schemas, unrename_tool_args

_PARAMS = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"$ref": "#/$defs/Query"},
        "batch": {"type": "array", "items": {"$ref": "#/$defs/Query"}},
        "target": {"anyOf": [{"type": "object", "properties": {"@id": {"type": "string"}}}, {"type": "string"}]},
        "legacy": {"$ref": "#/definitions/Old"},
        "$top": {"type": "integer"},
    },
    "$defs": {"Query": {"type": "object", "required": ["$filter"],
                        "properties": {"$filter": {"type": "string"}, "sub": {"$ref": "#/$defs/Query"}}}},
    "definitions": {"Old": {"type": "object", "properties": {"odd key": {"type": "string"}}}},
}


def _visible():
    return sanitize_tool_schemas([{"type": "function", "function": {"name": "t", "parameters": _PARAMS}}])[0][
        "function"]["parameters"]


def test_model_sees_renamed_nested_keys():
    visible = _visible()
    assert list(visible["$defs"]["Query"]["properties"]) == ["_filter", "sub"]
    assert list(visible["properties"]["target"]["anyOf"][0]["properties"]) == ["_id"]


def test_ref_target_keys_are_restored():
    assert unrename_tool_args(_PARAMS, {"query": {"_filter": "a eq 1"}, "_top": 5}) == {
        "query": {"$filter": "a eq 1"}, "$top": 5}


def test_ref_inside_array_items_and_nested_ref_are_restored():
    args = {"batch": [{"_filter": "x", "sub": {"_filter": "y"}}]}
    assert unrename_tool_args(_PARAMS, args) == {"batch": [{"$filter": "x", "sub": {"$filter": "y"}}]}


def test_union_branch_keys_are_restored_and_scalars_pass_through():
    assert unrename_tool_args(_PARAMS, {"target": {"_id": "7"}}) == {"target": {"@id": "7"}}
    assert unrename_tool_args(_PARAMS, {"target": "plain"}) == {"target": "plain"}


def test_legacy_definitions_ref_is_restored():
    assert unrename_tool_args(_PARAMS, {"legacy": {"odd_key": "v"}}) == {"legacy": {"odd key": "v"}}


def test_dangling_ref_leaves_args_untouched():
    schema = {"type": "object", "properties": {"q": {"$ref": "#/$defs/Missing"}}}
    assert unrename_tool_args(schema, {"q": {"_filter": "x"}}) == {"q": {"_filter": "x"}}
