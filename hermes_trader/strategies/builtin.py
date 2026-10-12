"""Built-in strategies. Each exposes a small parameter grid for the optimizer."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .. import indicators as ind
from .base import Strategy, latch


class SMACross(Strategy):
    name = "sma_cross"
    description = "Trend: long when fast SMA > slow SMA, short/flat otherwise."
    defaults = {"fast": 20, "slow": 50}
    grid = {"fast": [5, 10, 20, 30], "slow": [30, 50, 100, 200]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return 1 < p["fast"] < p["slow"]

    def targets(self, df: pd.DataFrame) -> pd.Series:
        f, s = ind.sma(df["close"], self.params["fast"]), ind.sma(df["close"], self.params["slow"])
        return (f > s).astype(float) - (f < s).astype(float)


class EMACross(SMACross):
    name = "ema_cross"
    description = "Trend: long when fast EMA > slow EMA, short/flat otherwise."
    grid = {"fast": [8, 12, 21, 34], "slow": [26, 55, 89, 144]}

    def targets(self, df: pd.DataFrame) -> pd.Series:
        f, s = ind.ema(df["close"], self.params["fast"]), ind.ema(df["close"], self.params["slow"])
        return (f > s).astype(float) - (f < s).astype(float)


class RSIReversion(Strategy):
    name = "rsi_reversion"
    description = "Mean reversion: buy oversold RSI, exit when RSI recovers; mirror for shorts."
    defaults = {"period": 14, "lower": 30, "upper": 70, "exit": 50}
    grid = {"period": [7, 14, 21], "lower": [20, 25, 30], "upper": [70, 75, 80], "exit": [45, 50, 55]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return 0 < p["lower"] < p["exit"] < p["upper"] < 100

    def warmup(self) -> int:
        return self.params["period"] * 3

    def targets(self, df: pd.DataFrame) -> pd.Series:
        r = ind.rsi(df["close"], self.params["period"])
        p = self.params
        long_ = latch(r < p["lower"], r > p["exit"], df.index, 1.0)
        short = latch(r > p["upper"], r < p["exit"], df.index, -1.0)
        return (long_ + short).clip(-1, 1)


class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    description = "Turtle-style breakout: long above N-bar high, exit below M-bar low; mirror for shorts."
    defaults = {"entry": 20, "exit": 10}
    grid = {"entry": [20, 40, 55, 100], "exit": [10, 20, 30]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return 1 < p["exit"] < p["entry"]

    def targets(self, df: pd.DataFrame) -> pd.Series:
        lo_e, hi_e = ind.donchian(df, self.params["entry"])
        lo_x, hi_x = ind.donchian(df, self.params["exit"])
        c = df["close"]
        long_ = latch(c > hi_e, c < lo_x, df.index, 1.0)
        short = latch(c < lo_e, c > hi_x, df.index, -1.0)
        return (long_ + short).clip(-1, 1)


class BollingerReversion(Strategy):
    name = "bollinger_reversion"
    description = "Mean reversion: buy below lower band, exit at middle band; mirror for shorts."
    defaults = {"period": 20, "k": 2.0}
    grid = {"period": [10, 20, 30, 50], "k": [1.5, 2.0, 2.5, 3.0]}

    def targets(self, df: pd.DataFrame) -> pd.Series:
        lo, mid, hi = ind.bollinger(df["close"], self.params["period"], self.params["k"])
        c = df["close"]
        long_ = latch(c < lo, c >= mid, df.index, 1.0)
        short = latch(c > hi, c <= mid, df.index, -1.0)
        return (long_ + short).clip(-1, 1)


class TrendFilteredRSI(Strategy):
    name = "trend_rsi"
    description = "Buy RSI dips only while price is above a long SMA (trend filter). Long-only."
    defaults = {"trend": 200, "period": 14, "lower": 35, "exit": 55}
    grid = {"trend": [100, 200], "period": [7, 14], "lower": [25, 30, 35, 40], "exit": [50, 55, 65]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return 0 < p["lower"] < p["exit"] < 100

    def targets(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        up = c > ind.sma(c, self.params["trend"])
        r = ind.rsi(c, self.params["period"])
        return latch(up & (r < self.params["lower"]), (r > self.params["exit"]) | ~up, df.index, 1.0)


BUILTINS: list[type[Strategy]] = [SMACross, EMACross, RSIReversion, DonchianBreakout, BollingerReversion, TrendFilteredRSI]
