"""Tool previews are built from whatever the model sent; a wrong-typed argument must not raise."""

import pytest

from agent.display import build_tool_label, build_tool_preview


@pytest.mark.parametrize("tool, args", [
    ("memory", {"action": "add", "target": "user", "content": None}),
    ("memory", {"action": "add", "target": "user", "content": ["a", "b"]}),
    ("memory", {"action": "replace", "target": "user", "old_text": 123}),
    ("send_message", {"target": "telegram", "message": None}),
    ("send_message", {"target": "telegram", "message": {"text": "hi"}}),
    ("todo_list", {"todos": 5}),
])
def test_wrong_typed_argument_still_yields_a_preview(tool, args):
    assert isinstance(build_tool_preview(tool, args), str)
    assert isinstance(build_tool_label(tool, args), str)


def test_well_typed_previews_are_unchanged():
    assert build_tool_preview("memory", {"action": "add", "target": "user", "content": "likes  tea"}) == '+user: "likes tea"'
    assert "2" in build_tool_preview("todo_list", {"todos": [{"id": 1}, {"id": 2}]})
