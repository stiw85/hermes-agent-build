"""A prompt queued behind a running turn runs with the content the client sent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import acp
import pytest
from acp.schema import (
    EmbeddedResourceContentBlock, ImageContentBlock, TextContentBlock, TextResourceContents,
)

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager

_IMAGE = ImageContentBlock(type="image", data="aGVsbG8=", mime_type="image/png")
_FILE = EmbeddedResourceContentBlock(
    type="resource", resource=TextResourceContents(uri="file:///w/plan.md", text="THE-ATTACHED-FILE-BODY"))


@pytest.mark.asyncio
@pytest.mark.parametrize("blocks,needle", [
    ([TextContentBlock(type="text", text="what is in this picture?"), _IMAGE], "data:image/png;base64,aGVsbG8="),
    ([_IMAGE], "data:image/png;base64,aGVsbG8="),
    ([TextContentBlock(type="text", text="review this"), _FILE], "THE-ATTACHED-FILE-BODY"),
])
async def test_prompt_queued_mid_turn_keeps_its_attachments(blocks, needle):
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    agent = HermesACPAgent(session_manager=manager)
    resp = await agent.new_session(cwd=".")
    state = manager.get_session(resp.session_id)
    state.agent._supports_active_turn_redirect = False
    seen = []
    state.agent.run_conversation = MagicMock(
        side_effect=lambda **kw: seen.append(kw["user_message"]) or {"final_response": "ok", "messages": []})
    conn = MagicMock(spec=acp.Client)
    conn.session_update = AsyncMock()
    agent._conn = conn

    state.is_running = True
    queued = await agent.prompt(prompt=blocks, session_id=resp.session_id)
    assert queued.stop_reason == "end_turn" and len(state.queued_prompts) == 1
    state.is_running = False
    await agent._drain_queued_prompts(state, resp.session_id, conn)

    assert len(seen) == 1 and needle in repr(seen[0])
    assert state.queued_prompts == []


@pytest.mark.asyncio
async def test_queued_text_prompt_still_runs_as_plain_text():
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    agent = HermesACPAgent(session_manager=manager)
    resp = await agent.new_session(cwd=".")
    state = manager.get_session(resp.session_id)
    state.agent._supports_active_turn_redirect = False
    seen = []
    state.agent.run_conversation = MagicMock(
        side_effect=lambda **kw: seen.append(kw["user_message"]) or {"final_response": "ok", "messages": []})
    conn = MagicMock(spec=acp.Client)
    conn.session_update = AsyncMock()
    agent._conn = conn

    state.is_running = True
    await agent.prompt(prompt=[TextContentBlock(type="text", text="and then this")], session_id=resp.session_id)
    state.is_running = False
    await agent._drain_queued_prompts(state, resp.session_id, conn)

    assert seen == ["and then this"]
