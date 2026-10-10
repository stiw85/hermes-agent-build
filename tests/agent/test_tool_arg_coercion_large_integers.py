"""String-typed integers are coerced exactly: ids above 2**53 (snowflakes, 64-bit
keys) must not be rounded on their way to the tool."""

import pytest

from tools.arg_coercion import _coerce_number, coerce_tool_args
from tools.registry import registry


@pytest.mark.parametrize("text", ["9007199254740993", "1234567890123456789", "-9223372036854775807"])
def test_large_integer_strings_keep_every_digit(text):
    assert _coerce_number(text, integer_only=True) == int(text)
    assert _coerce_number(text) == int(text)


def test_large_integer_argument_reaches_the_tool_unrounded():
    name = "zz_large_integer_probe"
    registry.register(
        name=name, toolset="zz_large_integer_probe", handler=lambda args, **kw: "{}",
        schema={"name": name, "description": "probe", "parameters": {
            "type": "object", "properties": {"message_id": {"type": "integer"}}}})
    try:
        args = coerce_tool_args(name, {"message_id": "1234567890123456789"})
    finally:
        registry.deregister(name)

    assert args["message_id"] == 1234567890123456789


@pytest.mark.parametrize("text,integer_only,expected", [
    ("42", True, 42), ("42.0", True, 42), ("42.5", True, "42.5"), ("1e3", True, 1000),
    ("3.14", False, 3.14), ("abc", True, "abc"), ("nan", False, "nan"), ("1e400", False, "1e400"),
])
def test_existing_number_coercions_are_unchanged(text, integer_only, expected):
    assert _coerce_number(text, integer_only=integer_only) == expected
