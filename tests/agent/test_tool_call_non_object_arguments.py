"""Replayed tool calls always carry an OBJECT input on the Anthropic and Bedrock wires.

A model can emit arguments that are valid JSON but not an object (``null``, ``[1]``, ``"x"``).
The call is refused at execution yet stays in history, and both wires require ``tool_use.input``
to be an object: forwarding the raw value rejected every later request of the session.
"""

import pytest

from agent.anthropic_message_convert import convert_messages_to_anthropic
from agent.bedrock_adapter import convert_messages_to_converse

NON_OBJECTS = ["null", "[1, 2]", '"README.md"', "42", "true"]


def _history(arguments):
    return [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search_files", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Tool arguments must be a valid JSON object"},
    ]


@pytest.mark.parametrize("arguments", NON_OBJECTS)
def test_anthropic_tool_use_input_is_an_object(arguments):
    _, messages = convert_messages_to_anthropic(_history(arguments), model="claude-sonnet-4-5")
    tool_use = messages[1]["content"][0]
    assert tool_use["type"] == "tool_use" and tool_use["input"] == {}


@pytest.mark.parametrize("arguments", NON_OBJECTS)
def test_bedrock_tool_use_input_is_an_object(arguments):
    _, messages = convert_messages_to_converse(_history(arguments))
    assert messages[1]["content"][0]["toolUse"]["input"] == {}


def test_object_arguments_are_forwarded_unchanged():
    history = _history('{"pattern": "*.py", "limit": 5}')
    _, anthropic_messages = convert_messages_to_anthropic(history, model="claude-sonnet-4-5")
    assert anthropic_messages[1]["content"][0]["input"] == {"pattern": "*.py", "limit": 5}
    _, converse_messages = convert_messages_to_converse(history)
    assert converse_messages[1]["content"][0]["toolUse"]["input"] == {"pattern": "*.py", "limit": 5}
