"""A frame carrying a lone surrogate still reaches a strict UTF-8 stdio peer.

``os.listdir`` hands back non-UTF-8 file names surrogate-escaped, so ordinary results
(path completion, tool output) can contain them.
"""

from __future__ import annotations

import io
import json
import logging
import threading

from tui_gateway.transport import StdioTransport, serialize_frame


def test_stdio_transport_writes_frame_with_lone_surrogate():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict", newline="\n")
    transport = StdioTransport(lambda: stream, threading.Lock())

    assert transport.write({"jsonrpc": "2.0", "id": 7, "result": {"items": [{"text": "caf\udce9.txt"}]}}) is True

    frame = json.loads(raw.getvalue().decode("utf-8"))
    assert frame["id"] == 7
    assert frame["result"]["items"][0]["text"] == "caf�.txt"


def test_serialized_frame_is_always_utf8_encodable():
    line = serialize_frame(
        {"jsonrpc": "2.0", "method": "event", "params": {"type": "message.delta", "payload": {"text": "ok \ud83d"}}},
        "test", logging.getLogger(__name__))

    assert json.loads(line.encode("utf-8"))["params"]["payload"]["text"] == "ok �"


def test_well_formed_astral_text_is_untouched():
    line = serialize_frame({"jsonrpc": "2.0", "id": 1, "result": {"text": "héllo 😀"}}, "test", logging.getLogger(__name__))

    assert json.loads(line)["result"]["text"] == "héllo 😀"
