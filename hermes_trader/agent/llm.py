"""Minimal OpenAI-compatible chat client with tool calling.

Works with OpenRouter, Nous Portal, OpenAI, Together, Groq, vLLM, llama.cpp,
Ollama (http://localhost:11434/v1) — anything that speaks /chat/completions.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, temperature: float = 0.2,
                 timeout: int = 60, session: requests.Session | None = None) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.s = session or requests.Session()

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> LLM:
        return cls(c["base_url"], c["model"], os.environ.get(c.get("api_key_env", "LLM_API_KEY")),
                   c.get("temperature", 0.2), c.get("timeout", 60))

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             json_mode: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
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
            if r.status_code in (429, 500, 502, 503, 504):
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
