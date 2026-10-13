"""Built-in strategies. Each exposes a small parameter grid for the optimizer."""

from __future__ import annotations

from typing import Any

import numpy as np
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


class FibRetracement(Strategy):
    name = "fib_retracement"
    description = ("Pullback: in an up-swing, buy when price dips to a Fibonacci retracement (38.2/50/61.8%) "
                   "and closes back above it; exit beyond the invalidation level (78.6%/100%) or at the swing "
                   "high / 127.2% extension. Mirror for shorts.")
    defaults = {"lookback": 55, "level": 0.618, "stop": 0.786, "target": 1.0, "min_range_atr": 3.0}
    grid = {"lookback": [34, 55, 89, 144], "level": [0.382, 0.5, 0.618], "stop": [0.786, 1.0], "target": [1.0, 1.272]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["lookback"] >= 5 and 0 < p["level"] < p["stop"] <= 1.0 and p["target"] >= 1.0 and p["min_range_atr"] >= 0

    def warmup(self) -> int:
        return max(self.params["lookback"], 14) + 2

    def targets(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        lo, hi, up = ind.swing(df, p["lookback"])
        rng = hi - lo
        big = rng >= p["min_range_atr"] * ind.atr(df).shift(1)  # ignore swings too small to be meaningful
        c, h, l_ = df["close"], df["high"], df["low"]
        upleg, downleg = (up == 1.0) & big, (up == 0.0) & big
        # up-leg: levels measured down from the swing high
        buy_lvl, buy_stop, buy_tp = hi - p["level"] * rng, hi - p["stop"] * rng, lo + p["target"] * rng
        long_ = latch(upleg & (l_ <= buy_lvl) & (c > buy_lvl), (c < buy_stop) | (c >= buy_tp), df.index, 1.0)
        # down-leg: levels measured up from the swing low
        sell_lvl, sell_stop, sell_tp = lo + p["level"] * rng, lo + p["stop"] * rng, hi - p["target"] * rng
        short = latch(downleg & (h >= sell_lvl) & (c < sell_lvl), (c > sell_stop) | (c <= sell_tp), df.index, -1.0)
        return (long_ + short).clip(-1, 1)


class MarketStructure(Strategy):
    name = "market_structure"
    description = ("Price action: confirmed swing highs/lows define structure. After a break of structure (close "
                   "above the last swing high), buy the retest of the broken level once it holds; exit when price "
                   "closes below the latest swing low (trailing). Mirror for shorts. trend=1 also requires a higher "
                   "low (lower high for shorts) before the break.")
    defaults = {"pivot": 3, "retest_bars": 12, "tol": 0.5, "trend": 1}
    grid = {"pivot": [2, 3, 5], "retest_bars": [6, 12, 24], "tol": [0.25, 0.5], "trend": [0, 1]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["pivot"] >= 1 and p["retest_bars"] >= 1 and p["tol"] > 0 and p["trend"] in (0, 1)

    def warmup(self) -> int:
        return max(30, 4 * self.params["pivot"] + 2)

    def targets(self, df: pd.DataFrame) -> pd.Series:
        k, rb, tol, need_trend = (self.params["pivot"], self.params["retest_bars"], self.params["tol"],
                                  bool(self.params["trend"]))
        h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        atr = ind.atr(df).to_numpy(float)
        n = len(df)
        out = np.zeros(n)
        nan = float("nan")
        last_ph = prev_ph = last_pl = prev_pl = nan
        arm_long = arm_short = None  # (level, last bar the retest may happen)
        pos = 0
        for t in range(n):
            i = t - k  # a pivot at bar i is confirmed once bar t = i + k has closed
            if i >= k:  # strictly beyond the k bars before it, at least level with the k after (no flat runs)
                if h[i] > h[i - k: i].max() and h[i] >= h[i + 1: t + 1].max():
                    prev_ph, last_ph = last_ph, h[i]
                if lo[i] < lo[i - k: i].min() and lo[i] <= lo[i + 1: t + 1].min():
                    prev_pl, last_pl = last_pl, lo[i]
            a = atr[t] if np.isfinite(atr[t]) else 0.0
            # exits: structure broken against the position (trailing swing stop)
            if pos > 0 and np.isfinite(last_pl) and c[t] < last_pl:
                pos = 0
            elif pos < 0 and np.isfinite(last_ph) and c[t] > last_ph:
                pos = 0
            # breaks of structure arm a retest entry
            if t > 0 and np.isfinite(last_ph) and c[t] > last_ph >= c[t - 1]:
                if not need_trend or (np.isfinite(prev_pl) and last_pl > prev_pl):
                    arm_long, arm_short = (last_ph, t + rb), None
            if t > 0 and np.isfinite(last_pl) and c[t] < last_pl <= c[t - 1]:
                if not need_trend or (np.isfinite(prev_ph) and last_ph < prev_ph):
                    arm_short, arm_long = (last_pl, t + rb), None
            # retest: price comes back to the broken level and closes on the right side of it
            if arm_long and a:
                lvl, until = arm_long
                if t > until or c[t] < lvl - tol * a:
                    arm_long = None  # no retest in time, or the breakout failed
                elif pos <= 0 and lo[t] <= lvl + tol * a and c[t] > lvl and not (c[t] > lvl >= c[t - 1]):
                    pos, arm_long = 1, None
            if arm_short and a:
                lvl, until = arm_short
                if t > until or c[t] > lvl + tol * a:
                    arm_short = None
                elif pos >= 0 and h[t] >= lvl - tol * a and c[t] < lvl and not (c[t] < lvl <= c[t - 1]):
                    pos, arm_short = -1, None
            out[t] = pos
        return pd.Series(out, index=df.index)


class FlowReversal(Strategy):
    name = "flow_reversal"
    description = ("Order flow (needs taker volume, e.g. Binance): at the low of the last N bars, a bar with heavy "
                   "net selling that still closes in its upper half (absorption), then within 3 bars a close above "
                   "that bar's high with net buying (initiation) -> long. Stop below the zone, target the prior "
                   "N-bar high. cvd=1 also needs a bullish CVD divergence. Mirror for shorts. Inactive without "
                   "order-flow data.")
    defaults = {"zone_bars": 48, "zone_atr": 1.0, "absorb": 0.15, "cvd": 0}
    grid = {"zone_bars": [24, 48, 96], "zone_atr": [0.5, 1.0], "absorb": [0.1, 0.2], "cvd": [0, 1]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["zone_bars"] >= 5 and p["zone_atr"] > 0 and 0 < p["absorb"] < 1 and p["cvd"] in (0, 1)

    def warmup(self) -> int:
        return 2 * self.params["zone_bars"] + 2

    def targets(self, df: pd.DataFrame) -> pd.Series:
        n = len(df)
        if not ind.has_flow(df, min(n, 50)):
            return pd.Series(0.0, index=df.index)
        p = self.params
        N, za, ab, need_cvd = p["zone_bars"], p["zone_atr"], p["absorb"], bool(p["cvd"])
        o, h, lo, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        share = np.divide(ind.delta(df).to_numpy(float), v, out=np.zeros(n), where=v > 0)
        atr = ind.atr(df).to_numpy(float)
        div = ind.cvd_divergence(df, N).to_numpy() if need_cvd else np.zeros(n, dtype=int)
        zl = pd.Series(lo).rolling(N).min().shift(1).to_numpy()  # zone from the previous N bars
        zh = pd.Series(h).rolling(N).max().shift(1).to_numpy()
        out = np.zeros(n)
        pos, stop, target = 0, 0.0, 0.0
        cand_long = cand_short = None  # (bar, level to clear, stop)
        for t in range(n):
            a = atr[t]
            if not (np.isfinite(a) and np.isfinite(zl[t]) and np.isfinite(zh[t])):
                out[t] = pos
                continue
            if pos > 0 and (c[t] < stop or c[t] >= target):
                pos = 0
            elif pos < 0 and (c[t] > stop or c[t] <= target):
                pos = 0
            mid = (h[t] + lo[t]) / 2
            # initiation: clears the absorption bar with aggression on our side
            if cand_long and t - cand_long[0] <= 3 and pos <= 0 and c[t] > cand_long[1] and share[t] > 0 \
                    and (not need_cvd or div[cand_long[0]: t + 1].max() > 0):
                pos, stop, target, cand_long = 1, cand_long[2], zh[t], None
            elif cand_short and t - cand_short[0] <= 3 and pos >= 0 and c[t] < cand_short[1] and share[t] < 0 \
                    and (not need_cvd or div[cand_short[0]: t + 1].min() < 0):
                pos, stop, target, cand_short = -1, cand_short[2], zl[t], None
            if cand_long and t - cand_long[0] > 3:
                cand_long = None
            if cand_short and t - cand_short[0] > 3:
                cand_short = None
            # absorption in the zone: heavy selling at the lows, yet the bar closes in its upper half
            if lo[t] <= zl[t] + za * a and share[t] <= -ab and c[t] >= mid:
                cand_long = (t, h[t], min(lo[t], zl[t]) - 0.25 * a)
            if h[t] >= zh[t] - za * a and share[t] >= ab and c[t] <= mid:
                cand_short = (t, lo[t], max(h[t], zh[t]) + 0.25 * a)
            out[t] = pos
        return pd.Series(out, index=df.index)


BUILTINS: list[type[Strategy]] = [SMACross, EMACross, RSIReversion, DonchianBreakout, BollingerReversion, TrendFilteredRSI,
                                  FibRetracement, MarketStructure, FlowReversal]
