"""Strategy contract.

A strategy maps an OHLCV DataFrame to a *target exposure* series in [-1, 1].
The value at bar t may only use information up to and including bar t's close;
the backtester fills it on bar t+1's open, so there is no look-ahead.
"""

from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from ..indicators import atr
from ..models import Signal


class Strategy(ABC):
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    defaults: ClassVar[dict[str, Any]] = {}
    grid: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"{self.name}: unknown params {sorted(unknown)}")
        self.params = {**self.defaults, **params}
        if not self.valid(self.params):
            raise ValueError(f"{self.name}: invalid params {self.params}")

    # --- override -------------------------------------------------------
    @abstractmethod
    def targets(self, df: pd.DataFrame) -> pd.Series:
        """Return target exposure per bar, index aligned with df, values in [-1, 1]."""

    @classmethod
    def valid(cls, params: dict[str, Any]) -> bool:
        return True

    def warmup(self) -> int:
        nums = [v for v in self.params.values() if isinstance(v, int)]
        return (max(nums) if nums else 0) + 2

    # --- shared ---------------------------------------------------------
    @classmethod
    def param_space(cls) -> list[dict[str, Any]]:
        if not cls.grid:
            return [dict(cls.defaults)]
        keys = list(cls.grid)
        combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(cls.grid[k] for k in keys))]
        return [{**cls.defaults, **c} for c in combos if cls.valid({**cls.defaults, **c})]

    def signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        if len(df) < self.warmup():
            return Signal(symbol, 0.0, self.name, 0.0, f"warming up ({len(df)}/{self.warmup()} bars)",
                          float(df["close"].iloc[-1]) if len(df) else 0.0)
        t = self.targets(df).fillna(0.0).clip(-1, 1)
        a = atr(df).iloc[-1]
        last = float(t.iloc[-1])
        prev = float(t.iloc[-2]) if len(t) > 1 else 0.0
        reason = f"{self.name}{self.params}: target {prev:+.2f} -> {last:+.2f}"
        return Signal(
            symbol=symbol,
            target=last,
            strategy=self.name,
            confidence=1.0,
            reason=reason,
            price=float(df["close"].iloc[-1]),
            atr=None if pd.isna(a) else float(a),
            meta={"params": dict(self.params)},
        )

    def __repr__(self) -> str:
        return f"{self.name}({self.params})"


def latch(entries: pd.Series, exits: pd.Series, index: pd.Index, value: float = 1.0) -> pd.Series:
    """Stateful position from boolean entry/exit events (entry wins on ties)."""
    ev = pd.Series(np.nan, index=index)
    ev[exits.fillna(False).astype(bool)] = 0.0
    ev[entries.fillna(False).astype(bool)] = value
    return ev.ffill().fillna(0.0)
