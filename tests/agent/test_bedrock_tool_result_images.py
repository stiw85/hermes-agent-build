"""Bedrock Converse tool results keep images as image blocks.

A list-type tool result (text + ``image_url`` parts from browser / vision tools) used to be
``json.dumps``-ed whole, so the base64 screenshot went out as hundreds of thousands of characters
of TEXT. The same parts in a user message already convert to a Converse ``image`` block.
"""

import base64

from agent.bedrock_adapter import convert_messages_to_converse

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


def _tool_result_blocks(content):
    _, messages = convert_messages_to_converse([
        {"role": "user", "content": "what is on screen?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "browser_vision", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": content},
    ])
    result = messages[2]["content"][0]["toolResult"]
    assert result["toolUseId"] == "t1"
    return result["content"]


def test_image_parts_become_image_blocks_not_base64_text():
    blocks = _tool_result_blocks([
        {"type": "text", "text": "Screenshot captured."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}},
    ])
    assert blocks[0] == {"text": "Screenshot captured."}
    assert blocks[1]["image"] == {"format": "png", "source": {"bytes": PNG_BYTES}}
    assert not any(PNG_B64[:64] in block.get("text", "") for block in blocks)


def test_non_part_tool_content_is_still_serialised_as_text():
    assert _tool_result_blocks("plain output") == [{"text": "plain output"}]
    assert _tool_result_blocks({"rows": 3}) == [{"text": '{"rows": 3}'}]
    assert _tool_result_blocks([{"name": "a"}, {"name": "b"}]) == [{"text": '[{"name": "a"}, {"name": "b"}]'}]


def test_jpg_media_type_maps_to_the_converse_jpeg_format():
    _, messages = convert_messages_to_converse([{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpg;base64,{PNG_B64}"}}]}])
    assert messages[0]["content"][0]["image"]["format"] == "jpeg"
