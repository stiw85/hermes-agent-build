"""Merge mode keeps the guarantees replace mode has: no item ends up with empty content,
a non-dict list item does not crash the write, and a rejected write changes nothing."""

import json

import pytest

from tools.todo_tool import TodoStore, todo_tool


@pytest.fixture()
def store():
    s = TodoStore()
    s.write([{"id": "1", "content": "first", "status": "in_progress"},
             {"id": "2", "content": "second", "status": "pending"}])
    return s


def test_merge_whitespace_content_keeps_existing_content(store):
    result = json.loads(todo_tool([{"id": "1", "content": "   ", "status": "completed"}], merge=True, store=store))

    assert result["todos"][0] == {"id": "1", "content": "first", "status": "completed"}


def test_merge_with_non_dict_item_applies_the_valid_items(store):
    before = store.snapshot()["revision"]

    result = json.loads(todo_tool([{"id": "1", "status": "completed"}, "junk", 7], merge=True, store=store))

    assert "error" not in result
    assert [t["status"] for t in result["todos"]] == ["completed", "pending"]
    assert result["revision"] == before + 1


def test_rejected_merge_leaves_list_and_revision_untouched(store):
    before = store.snapshot()

    result = json.loads(todo_tool(
        [{"id": "1", "status": "completed"}, {"id": "3", "content": ""}], merge=True, store=store))

    assert "error" in result
    assert store.snapshot() == before
