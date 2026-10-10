"""EventBridge delivery contracts against a real WAL-mode ``state.db``.

A gateway commit lands in ``state.db-wal``; the main file's mtime only moves at a checkpoint.
The poll gate must still open on that commit, or ``events_wait`` sits on a delivered message.
"""

import json
import time

import mcp_serve
from hermes_state import SessionDB

_KEY = "agent:main:telegram:dm:1"


def test_message_committed_to_the_wal_is_delivered_on_the_next_poll():
    writer = SessionDB()  # the gateway: a long-lived writer that has not checkpointed
    reader = None
    try:
        writer.create_session("s1", "telegram")
        writer.record_gateway_session_peer(
            "s1", source="telegram", user_id="u1", session_key=_KEY, chat_id="1", chat_type="dm")
        writer.append_message("s1", "user", "before the bridge started")

        bridge = mcp_serve.EventBridge()
        bridge._establish_baseline()
        reader = mcp_serve._get_session_db()
        bridge._poll_once(reader)  # settle the gate on the current files
        assert bridge.poll_events()["events"] == []

        time.sleep(0.05)  # filesystem timestamps are coarser than two back-to-back writes
        writer.append_message("s1", "user", "arrived live")
        bridge._poll_once(reader)

        assert [e["content"] for e in bridge.poll_events()["events"]] == ["arrived live"]
    finally:
        if reader is not None:
            reader.close()
        writer.close()


def test_events_wait_with_zero_timeout_returns_an_already_queued_event():
    bridge = mcp_serve.EventBridge()
    bridge._enqueue(mcp_serve.QueueEvent(0, "message", _KEY, {"content": "hi"}))

    assert bridge.wait_for_event(after_cursor=0, timeout_ms=0)["content"] == "hi"
    result = json.loads(mcp_serve._ToolHandlers(bridge).events_wait(timeout_ms=0))
    assert result["event"]["content"] == "hi"
    assert bridge.wait_for_event(after_cursor=1, timeout_ms=0) is None
