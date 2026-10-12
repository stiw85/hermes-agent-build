"""``session/list`` titles an untitled session by the TEXT of its first user message."""

from __future__ import annotations

from unittest.mock import MagicMock

from acp_adapter.session import SessionManager
from agent.session_persistence import _override_replaces_content

_IMAGE_URL = "data:image/png;base64," + "A" * 64
_MULTIMODAL = [{"type": "text", "text": "what is this?"}, {"type": "image_url", "image_url": {"url": _IMAGE_URL}}]


def test_live_user_row_keeps_native_image_blocks():
    """Why a title can meet list content at all: the adapter's plain-text persist override
    never replaces native image blocks in the transcript the turn hands back."""
    assert not _override_replaces_content({"role": "user"}, _MULTIMODAL, "what is this?")


def test_untitled_session_with_image_prompt_is_titled_by_its_text():
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    state = manager.create_session(cwd="/tmp")
    state.history = [{"role": "user", "content": _MULTIMODAL}, {"role": "assistant", "content": "a square"}]

    title = next(s["title"] for s in manager.list_sessions() if s["session_id"] == state.session_id)

    assert title == "what is this?"


def test_image_only_first_message_falls_through_to_the_next_text():
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    state = manager.create_session(cwd="/tmp")
    state.history = [{"role": "user", "content": [_MULTIMODAL[1]]}, {"role": "user", "content": "and now explain it"}]

    title = next(s["title"] for s in manager.list_sessions() if s["session_id"] == state.session_id)

    assert title == "and now explain it"
