"""The system message a session sends is byte-identical on every request, even after a memory write.

Provider prompt caches key on the system message, so one changed byte there re-bills the whole
prefix on every later call. ``agent._cached_system_prompt`` already makes the string stable inside
one process; these tests check what actually goes over the wire, through a real AIAgent and the
recording fake provider, and include the case the native-memory design depends on: a memory write
made mid-session must not change the system message of later requests in that session.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.core.history._helpers import NO_BACKGROUND_REVIEW, OFFLINE_CONFIG
from tests.fakes.fake_llm_provider import (
    FakeLLMServer,
    Text,
    ToolCall,
    write_hermes_home,
)


def _system_text(body: dict[str, Any]) -> str:
    """The text of the first system message, with cache markers and placement ignored."""
    messages = body["messages"]
    assert messages and messages[0]["role"] == "system", (
        "first message is not the system prompt"
    )
    content = messages[0]["content"]
    if isinstance(content, str):
        return content
    return "".join(
        part["text"] for part in content if isinstance(part, dict) and "text" in part
    )


@pytest.fixture
def relay():
    """A custom OpenAI-wire relay with prompt caching declared, the route where byte drift costs most."""
    home = Path(os.environ["HERMES_HOME"])
    srv = FakeLLMServer([]).__enter__()
    route = (
        f"custom_providers:\n  - name: cacherelay\n    base_url: {srv.base_url}\n    api_key: sk-fake-e2e\n"
        "    models:\n      fake-model:\n        prompt_caching: true\n"
    )
    write_hermes_home(
        home, srv.base_url, extra_config=OFFLINE_CONFIG + NO_BACKGROUND_REVIEW + route
    )
    yield srv, home
    srv.__exit__(None, None, None)


def _agent(srv, home):
    from hermes_state import SessionDB
    from run_agent import AIAgent

    return AIAgent(
        provider="custom:cacherelay",
        base_url=srv.base_url,
        api_key="sk-fake-e2e",
        model="fake-model",
        session_db=SessionDB(db_path=home / "state.db"),
        session_id="prompt-bytes",
        quiet_mode=True,
        platform="cli",
    )


def test_system_message_bytes_match_on_every_request_across_turns(relay):
    srv, home = relay
    srv.push(
        ToolCall("terminal", {"command": "echo one"}),
        Text("first done"),
        ToolCall("terminal", {"command": "echo two"}),
        Text("second done"),
        Text("third done"),
    )
    agent = _agent(srv, home)
    history: list[dict[str, Any]] = []
    for text in ("run a command", "run another", "summarise"):
        history = agent.run_conversation(
            text, conversation_history=history, task_id="t"
        )["messages"]
    agent.close()

    main = srv.main_requests()
    assert len(main) == 5
    texts = [_system_text(body) for body in main]
    assert texts[0], "the system prompt is empty"
    drifted = [i for i, text in enumerate(texts) if text != texts[0]]
    assert not drifted, f"system message changed on requests {drifted}"


def test_memory_write_mid_session_leaves_the_system_message_unchanged(relay):
    srv, home = relay
    note = "Prefers the metric system for all measurements."
    srv.push(
        Text("noted the first thing"),
        ToolCall("memory", {"action": "add", "target": "memory", "content": note}),
        Text("saved it"),
        Text("answered the third"),
    )
    agent = _agent(srv, home)
    history: list[dict[str, Any]] = []
    for text in ("first message", "please remember this", "third message"):
        history = agent.run_conversation(
            text, conversation_history=history, task_id="t"
        )["messages"]
    agent.close()

    # The write must have happened, or the assertions below prove nothing.
    from tools.memory_tool import get_memory_dir

    assert note in (get_memory_dir() / "MEMORY.md").read_text(encoding="utf-8"), (
        "the memory write did not persist"
    )
    main = srv.main_requests()
    texts = [_system_text(body) for body in main]
    assert len(texts) == 4
    assert texts[2] == texts[0], "a mid-session memory write changed the system message"
    assert texts[3] == texts[0]
    assert note not in texts[3], (
        "a mid-session write leaked into the frozen system prompt"
    )

    # Control: a new session in the same home builds its prompt from disk, so it does carry the note.
    # Without this, the absence above could just mean the note never reaches the prompt at all.
    srv.push(Text("fresh session"))
    fresh = _agent(srv, home)
    fresh.run_conversation("hello again", conversation_history=[], task_id="t2")
    fresh.close()
    assert note in _system_text(srv.main_requests()[-1]), (
        "a new session does not pick up the saved memory"
    )
