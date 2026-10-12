"""``nullable`` is consumed as a schema keyword only; a PARAMETER named ``nullable`` is an
ordinary argument the deferred-call validator must accept."""

import json

import pytest

from tools.registry import registry
from tools.tool_search_validation import validate_deferred_call_args

_NAME = "mcp__dbdemo__add_column"
_PARAMS = {
    "type": "object", "additionalProperties": False, "required": ["table", "column"],
    "properties": {
        "table": {"type": "string"}, "column": {"type": "string"},
        "nullable": {"type": "boolean", "description": "allow NULLs"},
        "default": {"type": "string", "nullable": True},
    },
}


@pytest.fixture()
def tool():
    registry.register(name=_NAME, toolset="mcp-dbdemo",
                      schema={"name": _NAME, "description": "add a column", "parameters": _PARAMS},
                      handler=lambda args, **kw: "{}")
    yield _NAME
    registry.deregister(_NAME)


def test_argument_named_nullable_is_accepted(tool):
    assert validate_deferred_call_args(tool, {"table": "t", "column": "c", "nullable": True}) is None


def test_argument_named_nullable_is_still_type_checked(tool):
    error = validate_deferred_call_args(tool, {"table": "t", "column": "c", "nullable": {"x": 1}})
    assert error is not None and json.loads(error)["path"] == "arguments.nullable"


def test_nullable_keyword_still_admits_null(tool):
    assert validate_deferred_call_args(tool, {"table": "t", "column": "c", "default": None}) is None
