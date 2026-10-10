"""Output budgets read from provider overflow errors that state both the window and the input.

Sibling of :mod:`agent.model_metadata`: each helper returns ``window - measured input`` (the room
left for ``max_tokens``), or None when the wording is absent or the input alone fills the window
(a genuine input overflow -> compress).
"""

import re
from typing import Optional

# OpenAI's original overflow wording, copied by vLLM / llama-cpp-python: "(36865 in the messages,
# 65536 in the completion)"; legacy completions: "(771 in your prompt; 4000 for the completion)".
# The first figure is the prompt the server MEASURED, the second the requested max_tokens.
_COMPLETION_SPLIT_RE = re.compile(
    r'\((\d+)\s+(?:tokens\s+)?in (?:the messages|your prompt|the prompt)\s*[;,]\s*'
    r'(\d+)\s+(?:tokens\s+)?(?:in|for) the completion\)'
)
# Anthropic: "input length and `max_tokens` exceed context limit: 188240 + 21333 > 200000" is
# measured input + requested max_tokens > window.
_SUM_OVER_LIMIT_RE = re.compile(r'exceed context limit:\s*(\d+)\s*\+\s*\d+\s*>\s*(\d+)')


def _budget(window: int, measured_input: int) -> Optional[int]:
    available = window - measured_input
    return available if available >= 1 else None


def completion_split_budget(error_lower: str) -> Optional[int]:
    """Budget from the OpenAI-style parenthetical split."""
    split = _COMPLETION_SPLIT_RE.search(error_lower)
    ctx = re.search(r'maximum context length is (\d+)', error_lower)
    if not split or not ctx:
        return None
    return _budget(int(ctx.group(1)), int(split.group(1)))


def sum_over_limit_budget(error_lower: str) -> Optional[int]:
    """Budget from Anthropic's ``input + max_tokens > window`` wording."""
    match = _SUM_OVER_LIMIT_RE.search(error_lower)
    return _budget(int(match.group(2)), int(match.group(1))) if match else None
