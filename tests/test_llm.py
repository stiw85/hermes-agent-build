"""LLM providers: OpenAI-compatible and native Anthropic (message/tool translation, auth, factory)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_trader.agent.llm import (
    LLM,
    AnthropicLLM,
    LLMError,
    detect_provider,
    from_anthropic,
    llm_from_config,
    to_anthropic,
    tools_to_anthropic,
)
from hermes_trader.config import DEFAULTS


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body
        self.text = json.dumps(body)

    def json(self):
        return self._b


class Session:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        r = self.replies.pop(0)
        return r if isinstance(r, Resp) else Resp(200, r)


TOOL = {"type": "function", "function": {"name": "get_price", "description": "price",
                                         "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}}}}


def test_translation_round_trip():
    msgs = [
        {"role": "system", "content": "S1"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "checking", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "a", "arguments": '{"x": 1}'}},
            {"id": "t2", "type": "function", "function": {"name": "b", "arguments": "not json"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "r1"},
        {"role": "tool", "tool_call_id": "t2", "content": "r2"},
        {"role": "user", "content": "Tool budget exhausted. Summarise now."},
    ]
    system, out = to_anthropic(msgs)
    assert system == "S1"
    assert [m["role"] for m in out] == ["user", "assistant", "user"]  # strictly alternating
    assert out[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "a", "input": {"x": 1}}
    assert out[1]["content"][2]["input"] == {}
    last = out[2]["content"]  # both tool results + the follow-up text merged into one user turn
    assert [b["type"] for b in last] == ["tool_result", "tool_result", "text"]
    assert last[0]["tool_use_id"] == "t1"
    assert tools_to_anthropic([TOOL])[0]["input_schema"]["properties"]["symbol"]["type"] == "string"
    msg = from_anthropic({"content": [{"type": "text", "text": "ok "}, {"type": "tool_use", "id": "u1",
                                                                         "name": "get_price", "input": {"symbol": "X"}}]})
    assert msg["content"] == "ok " and json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"symbol": "X"}


def test_anthropic_request_shape_and_json_mode():
    s = Session([{"content": [{"type": "text", "text": '{"verdict":"approve"}'}]}])
    llm = AnthropicLLM("claude-haiku-5-5", "sk-ant-api-test", "https://api.anthropic.com/v1", session=s)
    out = llm.chat([{"role": "system", "content": "review"}, {"role": "user", "content": "trade?"}],
                   tools=[TOOL], json_mode=True)
    c = s.calls[0]
    assert c["url"] == "https://api.anthropic.com/v1/messages"
    assert c["headers"]["x-api-key"] == "sk-ant-api-test" and "Authorization" not in c["headers"]
    assert c["headers"]["anthropic-version"]
    b = c["json"]
    assert b["model"] == "claude-haiku-5-5" and b["max_tokens"] == 4096
    assert "temperature" not in b  # newer Claude models reject non-default temperature
    assert b["system"].startswith("review") and "JSON object" in b["system"]
    assert b["tools"][0]["name"] == "get_price" and b["tool_choice"] == {"type": "auto"}
    assert out["content"] == '{"verdict":"approve"}'


def test_anthropic_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(LLMError, match="key missing"):
        AnthropicLLM("m", None, session=Session([])).chat([{"role": "user", "content": "x"}])
    with pytest.raises(LLMError, match="not a Claude.ai login"):
        AnthropicLLM("m", "bad", session=Session([Resp(401, {"error": "x"})])).chat([{"role": "user", "content": "x"}])
    s = Session([Resp(529, {}), {"content": [{"type": "text", "text": "back"}]}])  # overloaded, then fine
    assert AnthropicLLM("m", "k", session=s).chat([{"role": "user", "content": "x"}])["content"] == "back"


def test_provider_factory(monkeypatch):
    base = dict(DEFAULTS["llm"])
    assert detect_provider(base) == "openai"
    assert detect_provider({**base, "base_url": "https://api.anthropic.com"}) == "anthropic"
    assert detect_provider({**base, "provider": "anthropic"}) == "anthropic"
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    a = llm_from_config({**base, "provider": "anthropic", "base_url": "https://api.anthropic.com",
                         "model": "claude-sonnet-5-5"})
    assert isinstance(a, AnthropicLLM) and a.key == "sk-ant-api-x" and a.model == "claude-sonnet-5-5"
    monkeypatch.setenv("LLM_API_KEY", "primary")
    assert llm_from_config({**base, "provider": "anthropic"}).key == "primary"
    o = llm_from_config({**base, "temperature": None})
    assert isinstance(o, LLM) and o.temperature is None
    s = Session([{"choices": [{"message": {"content": "hi"}}]}])
    o.s = s
    o.chat([{"role": "user", "content": "x"}])
    assert "temperature" not in s.calls[0]["json"]


def test_agent_loop_over_anthropic():
    """The tool-calling agent works unchanged on top of the Anthropic client."""
    from hermes_trader.agent.loop import Agent

    class TK:
        class e:
            class cfg:
                home = Path(".")

        class lessons:
            @staticmethod
            def render():
                return ""

        class playbooks:
            @staticmethod
            def index():
                return ""

        def schemas(self, names):
            return [TOOL]

        def call(self, name, args):
            return json.dumps({"price": 100, "symbol": args.get("symbol")})

    s = Session([
        {"content": [{"type": "tool_use", "id": "u1", "name": "get_price", "input": {"symbol": "BTC/USDT"}}]},
        {"content": [{"type": "text", "text": "BTC is 100."}]},
    ])
    agent = Agent(AnthropicLLM("m", "k", session=s), TK())
    assert agent.run("price?") == "BTC is 100."
    second = s.calls[1]["json"]["messages"]
    assert second[-1]["content"][0] == {"type": "tool_result", "tool_use_id": "u1",
                                        "content": '{"price": 100, "symbol": "BTC/USDT"}'}


def test_cli_llm_check(monkeypatch, tmp_path, capsys):
    from hermes_trader import cli

    s = Session([
        {"content": [{"type": "tool_use", "id": "u1", "name": "get_price", "input": {"symbol": "BTC/USDT"}}]},
        {"content": [{"type": "text", "text": "65000"}]},
    ])
    monkeypatch.setattr("requests.Session", lambda: s)
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-api-x")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"home: {tmp_path}\nllm:\n  provider: anthropic\n  base_url: https://api.anthropic.com\n"
                   "  model: claude-haiku-5-5\n")
    assert cli.main(["-c", str(cfg), "llm"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["tool_calling"] and out["provider"] == "anthropic" and out["reply"] == "65000"
