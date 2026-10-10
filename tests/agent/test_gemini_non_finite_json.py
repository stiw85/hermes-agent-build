"""Native Gemini requests stay serialisable when tool output carries NaN / Infinity.

Python's ``json.dumps`` writes ``NaN`` / ``Infinity`` for non-finite floats and ``json.loads``
reads them back, but they are not JSON on the wire: httpx refuses to encode the request. A tool
result (or replayed tool-call arguments) holding one made every request of the session raise
before it was sent. Such payloads go out as opaque text instead.
"""

import json

import httpx
import pytest

from agent.gemini_native_adapter import GeminiNativeClient, build_gemini_request


def _history(tool_output: str, arguments: str = "{}") -> list[dict]:
    return [
        {"role": "user", "content": "stats?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "execute_code", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": "c1", "content": tool_output},
    ]


def _wire_body(request: dict) -> str:
    """Encode the way httpx does for ``json=``: strict JSON, no NaN / Infinity."""
    return json.dumps(request, allow_nan=False)


@pytest.mark.parametrize("tool_output", [
    json.dumps({"mean": float("nan"), "rows": 3}),
    json.dumps({"max": float("inf"), "min": float("-inf")}),
    '{"overflow": 1e999}',
])
def test_non_finite_tool_result_is_sent_as_opaque_text(tool_output):
    request = build_gemini_request(messages=_history(tool_output), model="gemini-3-pro")
    _wire_body(request)
    response = request["contents"][2]["parts"][0]["functionResponse"]["response"]
    assert response == {"output": tool_output}


def test_finite_structured_tool_result_stays_structured():
    request = build_gemini_request(messages=_history('{"mean": 1.5, "rows": 3}'), model="gemini-3-pro")
    assert request["contents"][2]["parts"][0]["functionResponse"]["response"] == {"mean": 1.5, "rows": 3}


def test_non_finite_tool_call_arguments_do_not_break_the_request():
    request = build_gemini_request(messages=_history("ok", arguments='{"threshold": NaN}'), model="gemini-3-pro")
    _wire_body(request)
    assert request["contents"][1]["parts"][0]["functionCall"]["args"] == {"_raw": '{"threshold": NaN}'}


def test_client_sends_the_request_instead_of_raising():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]})

    client = GeminiNativeClient(api_key="AQ.test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = client.chat.completions.create(
        model="gemini-3-pro", messages=_history(json.dumps({"mean": float("nan")})),
    )
    assert response.choices[0].message.content == "ok"
    assert len(sent) == 1
