"""A tool result made of text parts reaches Anthropic as text, not as the JSON source of the list.

Image eviction and the image-rejection strip leave a tool message whose content is a list of text
parts. The converter only produced blocks when an image survived, so the model was shown
``[{"type": "text", "text": "line\\nline"}]`` with escaped newlines and quotes.
"""

from agent.anthropic_message_convert import convert_messages_to_anthropic
from agent.context_compressor import _strip_images_from_tool_msg

HEAD = [
    {"role": "user", "content": "take a screenshot"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "computer", "arguments": "{}"}}]},
]


def _tool_result(content):
    _, messages = convert_messages_to_anthropic(
        HEAD + [{"role": "tool", "tool_call_id": "c1", "content": content}], model="claude-sonnet-4-5",
    )
    return messages[2]["content"][0]["content"]


def test_text_parts_become_text_blocks():
    assert _tool_result([{"type": "text", "text": 'Screenshot captured.\nWindow title: "Settings"'}]) == [
        {"type": "text", "text": 'Screenshot captured.\nWindow title: "Settings"'},
    ]


def test_evicted_screenshot_keeps_its_caption_readable():
    evicted = _strip_images_from_tool_msg({"role": "tool", "tool_call_id": "c1", "content": [
        {"type": "text", "text": "Screenshot captured.\nWindow title: \"Settings\""},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
    ]})
    blocks = _tool_result(evicted["content"])
    assert [block["type"] for block in blocks] == ["text", "text"]
    assert blocks[0]["text"] == 'Screenshot captured.\nWindow title: "Settings"'


def test_json_array_tool_output_is_still_serialised():
    assert _tool_result([{"name": "a"}, {"name": "b"}]) == '[{"name": "a"}, {"name": "b"}]'
