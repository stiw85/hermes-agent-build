"""The reactive ``pattern``/``format`` strip removes schema KEYWORDS, never a tool's parameters
(or ``$defs`` entries) that happen to carry those names."""

from tools.schema_sanitizer import strip_pattern_and_format


def _tool(properties, **extra):
    return [{"type": "function", "function": {"name": "export_report", "parameters": {
        "type": "object", "properties": properties, **extra}}}]


def test_parameters_named_format_and_pattern_survive_beside_one_named_type():
    tools = _tool({
        "type": {"type": "string", "enum": ["sales", "usage"]},
        "format": {"type": "string", "enum": ["pdf", "csv"]},
        "pattern": {"type": "string", "description": "glob of rows to include"},
        "date": {"type": "string", "format": "date", "pattern": r"^\d{4}"},
    }, required=["type", "format"])

    out, stripped = strip_pattern_and_format(tools)

    params = out[0]["function"]["parameters"]
    assert list(params["properties"]) == ["type", "format", "pattern", "date"]
    assert params["properties"]["date"] == {"type": "string"}
    assert params["properties"]["format"]["enum"] == ["pdf", "csv"]
    assert stripped == 2


def test_keywords_inside_defs_are_stripped_but_a_def_named_format_survives():
    tools = _tool({"when": {"$ref": "#/$defs/format"}},
                  **{"$defs": {"type": {"type": "string"},
                               "format": {"type": "string", "format": "date-time"}}})

    out, stripped = strip_pattern_and_format(tools)

    defs = out[0]["function"]["parameters"]["$defs"]
    assert defs["format"] == {"type": "string"}
    assert stripped == 1

