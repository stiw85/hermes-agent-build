from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hermes_trader.config import load_config


def make_df(n: int = 600, seed: int = 1, trend: float = 0.0005, vol: float = 0.01, start: float = 100.0,
            freq: str = "1h") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(trend + vol * rng.standard_normal(n)))
    open_ = np.concatenate([[start], close[:-1]])
    idx = pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC", name="ts")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.002,
                         "low": np.minimum(open_, close) * 0.998, "close": close, "volume": 1.0}, index=idx)


@pytest.fixture
def df() -> pd.DataFrame:
    return make_df()


@pytest.fixture
def cfg(tmp_path: Path):
    return load_config(overrides={"home": str(tmp_path / "home")}, path=None)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 30, tzinfo=timezone.utc)


class FakeLLM:
    """Scripted OpenAI-style replies. Each item: str (content) or list of (tool_name, args)."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, json_mode=False):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "json_mode": json_mode})
        item = self.script.pop(0) if self.script else "done"
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return {"role": "assistant", "content": item}
        import json

        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(item)]}
