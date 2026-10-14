"""LLM clients with tool calling.

Two providers, one interface (`chat(messages, tools, json_mode) -> OpenAI-style message`):

- ``openai`` (default): anything that speaks ``/chat/completions`` — OpenRouter, Nous Portal,
  OpenAI, Together, Groq, DeepSeek, vLLM, llama.cpp, Ollama (http://localhost:11434/v1).
- ``anthropic``: Claude via Anthropic's native Messages API with a Claude Console API key.
  Messages and tool calls are translated both ways, so the agent loop never sees the difference.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests


class LLMError(RuntimeError):
    pass


RETRY_STATUS = (429, 500, 502, 503, 504, 529)  # 529 = Anthropic "overloaded"


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, temperature: float | None = 0.2,
                 timeout: int = 60, session: requests.Session | None = None) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.s = session or requests.Session()

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> LLM | AnthropicLLM:
        return llm_from_config(c)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             json_mode: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        last = ""
        for attempt in range(3):
            try:
                r = self.s.post(self.url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(2**attempt)
                continue
            if r.status_code in RETRY_STATUS:
                last = f"{r.status_code}: {r.text[:200]}"
                time.sleep(2**attempt)
                continue
            if r.status_code == 400 and json_mode:  # some servers reject response_format
                body.pop("response_format", None)
                json_mode = False
                continue
            if r.status_code >= 400:
                raise LLMError(f"{r.status_code}: {r.text[:300]}")
            choice = r.json()["choices"][0]["message"]
            return choice
        raise LLMError(f"LLM unavailable: {last}")


# ---- Anthropic (native Messages API) -----------------------------------------------------------

ANTHROPIC_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
JSON_ONLY = "Reply with one JSON object only: no prose, no code fences."


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI chat messages -> (system, Anthropic messages).

    System messages are hoisted; assistant tool_calls become tool_use blocks; role=tool results become
    tool_result blocks in a user turn; consecutive same-role turns are merged (Anthropic requires the
    roles to alternate).
    """
    system: list[str] = []
    out: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            if content:
                system.append(str(content))
        elif role == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                           "content": str(content or "")}])
        elif role == "assistant":
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            for c in m.get("tool_calls") or []:
                fn = c.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": c.get("id", ""), "name": fn.get("name", ""),
                               "input": args if isinstance(args, dict) else {}})
            push("assistant", blocks)
        else:  # user
            push("user", [{"type": "text", "text": str(content)}] if content else [])
    if out and out[0]["role"] != "user":  # the API wants a user turn first
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continue)"}]})
    return "\n\n".join(system), out


def tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append({"name": fn["name"], "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
    return out


def from_anthropic(resp: dict[str, Any]) -> dict[str, Any]:
    """Anthropic response -> OpenAI-style assistant message."""
    text, calls = [], []
    for b in resp.get("content") or []:
        if b.get("type") == "text":
            text.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            calls.append({"id": b.get("id", ""), "type": "function",
                          "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input") or {})}})
    msg: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
    if calls:
        msg["tool_calls"] = calls
    return msg


class AnthropicLLM:
    """Claude through the native Messages API (x-api-key auth, a Claude Console API key)."""

    def __init__(self, model: str, api_key: str | None, base_url: str = ANTHROPIC_URL, timeout: int = 60,
                 max_tokens: int = 4096, temperature: float | None = None, key_hint: str = "",
                 session: requests.Session | None = None) -> None:
        base = (base_url or ANTHROPIC_URL).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.url = base + "/v1/messages"
        self.model = model
        self.key = api_key
        self.key_hint = key_hint
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature  # None = model default (newer Claude models reject other values)
        self.s = session or requests.Session()

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             json_mode: bool = False) -> dict[str, Any]:
        if not self.key:
            raise LLMError(f"Anthropic API key missing. {self.key_hint}".strip())
        system, msgs = to_anthropic(messages)
        if json_mode:
            system = f"{system}\n\n{JSON_ONLY}" if system else JSON_ONLY
        body: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "messages": msgs}
        if system:
            body["system"] = system
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = tools_to_anthropic(tools)
            body["tool_choice"] = {"type": "auto"}
        headers = {"x-api-key": self.key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        last = ""
        for attempt in range(3):
            try:
                r = self.s.post(self.url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(2**attempt)
                continue
            if r.status_code in RETRY_STATUS:
                last = f"{r.status_code}: {r.text[:200]}"
                time.sleep(2**attempt)
                continue
            if r.status_code == 401:
                raise LLMError("401 from Anthropic: the API key was rejected. Use a key from "
                               "platform.claude.com → API keys (starts with sk-ant-api…), not a Claude.ai login.")
            if r.status_code >= 400:
                raise LLMError(f"{r.status_code}: {r.text[:300]}")
            return from_anthropic(r.json())
        raise LLMError(f"Anthropic unavailable: {last}")


def detect_provider(c: dict[str, Any]) -> str:
    p = str(c.get("provider") or "auto").lower()
    if p in ("openai", "anthropic"):
        return p
    host = urlparse(str(c.get("base_url") or "")).hostname or ""
    return "anthropic" if host.endswith("anthropic.com") else "openai"


def llm_from_config(c: dict[str, Any]) -> LLM | AnthropicLLM:
    from ..config import missing_secret_hint

    env = c.get("api_key_env", "LLM_API_KEY")
    key = os.environ.get(env) or None
    if detect_provider(c) == "anthropic":
        key = key or os.environ.get("ANTHROPIC_API_KEY") or None
        return AnthropicLLM(c.get("model") or "claude-haiku-5-5", key, c.get("base_url") or ANTHROPIC_URL,
                            c.get("timeout", 60), c.get("max_tokens", 4096), c.get("anthropic_temperature"),
                            key_hint=missing_secret_hint(env))
    return LLM(c["base_url"], c["model"], key, c.get("temperature", 0.2), c.get("timeout", 60))


def parse_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates code fences / prose)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])
