"""An assistant message carrying ``tool_calls: null`` converts on the Anthropic wire.

OpenAI SDK ``model_dump()`` output writes ``"tool_calls": None`` for a plain assistant turn, and
auxiliary / plugin routes reach the converter without the main loop's sanitizer. The
chat-completions, Bedrock and Gemini paths all read it as "no tool calls".
"""

import pytest

from agent.anthropic_adapter import build_anthropic_kwargs


@pytest.mark.parametrize("tool_calls", [None, []])
def test_absent_tool_calls_convert_to_a_plain_text_turn(tool_calls):
    kwargs = build_anthropic_kwargs("claude-haiku-4-5", [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "tool_calls": tool_calls},
        {"role": "user", "content": "again"},
    ], None, 1024, None)
    assert kwargs["messages"][1] == {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}
