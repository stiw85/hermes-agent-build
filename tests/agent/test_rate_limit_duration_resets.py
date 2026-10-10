"""``x-ratelimit-reset-*`` headers written as durations are read as seconds.

OpenAI and Groq send the reset as a Go-style duration (``1s``, ``6m0s``, ``1m30s``, ``6ms``)
where the Nous Portal sends plain seconds. The duration form parsed to 0, so ``/usage`` showed
every bucket on those providers as "resets in 0s".
"""

import pytest

from agent.rate_limit_tracker import format_rate_limit_display, parse_rate_limit_headers


def _reset(value: str) -> float:
    state = parse_rate_limit_headers({"x-ratelimit-limit-tokens": "1000", "x-ratelimit-reset-tokens": value})
    assert state is not None
    return state.tokens_min.reset_seconds


@pytest.mark.parametrize("value, seconds", [
    ("1s", 1.0), ("6m0s", 360.0), ("1m30s", 90.0), ("2m59.56s", 179.56), ("1h0m0s", 3600.0),
    ("6ms", 0.006), ("1h", 3600.0), ("42.3", 42.3), ("90", 90.0),
])
def test_reset_header_is_read_in_seconds(value, seconds):
    assert _reset(value) == pytest.approx(seconds)


@pytest.mark.parametrize("value", ["", "soon", "m", "1x"])
def test_unreadable_reset_stays_zero(value):
    assert _reset(value) == 0.0


def test_usage_display_names_the_real_reset_window():
    state = parse_rate_limit_headers({
        "x-ratelimit-limit-tokens": "150000", "x-ratelimit-remaining-tokens": "149984",
        "x-ratelimit-reset-tokens": "6m0s",
    }, provider="openai")
    tokens_line = next(line for line in format_rate_limit_display(state).splitlines() if "Tokens/min" in line)
    assert "resets in 5m" in tokens_line or "resets in 6m" in tokens_line
