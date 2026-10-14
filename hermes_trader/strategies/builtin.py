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
    needs_flow = True
    defaults = {"zone_bars": 48, "zone_atr": 1.0, "absorb": 0.15, "cvd": 0}
    grid = {"zone_bars": [24, 48, 96], "zone_atr": [0.5, 1.0], "absorb": [0.1, 0.2], "cvd": [0, 1]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["zone_bars"] >= 5 and p["zone_atr"] > 0 and 0 < p["absorb"] < 1 and p["cvd"] in (0, 1)

    def warmup(self) -> int:
        return 2 * self.params["zone_bars"] + 2

    def targets(self, df: pd.DataFrame) -> pd.Series:
        n = len(df)
        if "taker_buy" not in df.columns:
            return pd.Series(0.0, index=df.index)
        p = self.params
        N, za, ab, need_cvd = p["zone_bars"], p["zone_atr"], p["absorb"], bool(p["cvd"])
        o, h, lo, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        tb = df["taker_buy"].to_numpy(float)
        ok = np.isfinite(tb) & (v > 0)  # bars with usable order flow; others can't start or confirm a setup
        share = np.divide(2 * np.nan_to_num(tb) - v, v, out=np.zeros(n), where=ok)
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
            if not ok[t]:  # no order flow on this bar: exits above still ran; no new setups or entries
                out[t] = pos
                continue
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


# ---- shared pivot machinery for the chart-pattern strategies -----------------------------------------

def _confirmed_pivot(h: np.ndarray, lo: np.ndarray, t: int, k: int) -> tuple[str, int, float] | None:
    """Pivot at bar i = t - k, confirmed now: strictly beyond the k bars before, level-or-beyond the k after.

    Returns ("H", i, high) or ("L", i, low); "H" wins if a bar is both (rare outside bar).
    """
    i = t - k
    if i < k:
        return None
    if h[i] > h[i - k: i].max() and h[i] >= h[i + 1: t + 1].max():
        return ("H", i, float(h[i]))
    if lo[i] < lo[i - k: i].min() and lo[i] <= lo[i + 1: t + 1].min():
        return ("L", i, float(lo[i]))
    return None


def _zigzag_add(zz: list[tuple[str, int, float]], p: tuple[str, int, float]) -> None:
    """Keep an alternating high/low swing list; a same-side pivot replaces the last one if more extreme."""
    if zz and zz[-1][0] == p[0]:
        if (p[0] == "H" and p[2] >= zz[-1][2]) or (p[0] == "L" and p[2] <= zz[-1][2]):
            zz[-1] = p
        return
    zz.append(p)
    if len(zz) > 12:
        del zz[0]


class SIDMethod(Strategy):
    name = "sid_method"
    description = ("SID Method (Sid Naiman, The Trading Cafe): RSI below `lower` sets up a long; enter when RSI and "
                   "MACD both turn up within `setup_bars`. Stop at the lowest low since the signal; exit when RSI "
                   "reaches `exit`. Mirror for shorts above `upper`. trend_guard=1 refuses shorts while price is "
                   "above a rising 200 SMA (and longs below a falling one).")
    defaults = {"period": 14, "lower": 30, "upper": 70, "exit": 50, "setup_bars": 10, "trend_guard": 1}
    grid = {"period": [7, 14], "lower": [25, 30], "upper": [70, 75], "setup_bars": [5, 10], "trend_guard": [0, 1]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return 0 < p["lower"] < p["exit"] < p["upper"] < 100 and p["setup_bars"] >= 1 and p["trend_guard"] in (0, 1)

    def warmup(self) -> int:
        return max(3 * self.params["period"], 40)

    def targets(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        c, h, lo = (df[k].to_numpy(float) for k in ("close", "high", "low"))
        r = ind.rsi(df["close"], p["period"]).to_numpy(float)
        m = ind.macd(df["close"])[0].to_numpy(float)
        sma = ind.sma(df["close"], 200).to_numpy(float)
        n = len(df)
        out = np.zeros(n)
        pos, stop = 0, 0.0
        long_sig = short_sig = None  # [last extreme bar, extreme price since the signal]
        for t in range(1, n):
            if not (np.isfinite(r[t]) and np.isfinite(r[t - 1]) and np.isfinite(m[t]) and np.isfinite(m[t - 1])):
                continue
            # exits: RSI back to the midline (no exceptions), or the structural stop
            if pos > 0 and (r[t] >= p["exit"] or c[t] < stop):
                pos = 0
            elif pos < 0 and (r[t] <= p["exit"] or c[t] > stop):
                pos = 0
            # setups: an RSI extreme starts (or refreshes) the signal; track the extreme price since then
            if r[t] < p["lower"]:
                long_sig = [t, min(lo[t], long_sig[1]) if long_sig else lo[t]]
            elif long_sig:
                long_sig[1] = min(long_sig[1], lo[t])
            if r[t] > p["upper"]:
                short_sig = [t, max(h[t], short_sig[1]) if short_sig else h[t]]
            elif short_sig:
                short_sig[1] = max(short_sig[1], h[t])
            if long_sig and t - long_sig[0] > p["setup_bars"]:
                long_sig = None
            if short_sig and t - short_sig[0] > p["setup_bars"]:
                short_sig = None
            up_trend = np.isfinite(sma[t]) and c[t] > sma[t] and sma[t] > sma[max(0, t - 20)]
            down_trend = np.isfinite(sma[t]) and c[t] < sma[t] and sma[t] < sma[max(0, t - 20)]
            # entry: both RSI and MACD pointing the trade's way
            if long_sig and pos <= 0 and r[t] > r[t - 1] and m[t] > m[t - 1] and r[t] < p["exit"] \
                    and not (p["trend_guard"] and down_trend):
                pos, stop, long_sig = 1, long_sig[1], None
            elif short_sig and pos >= 0 and r[t] < r[t - 1] and m[t] < m[t - 1] and r[t] > p["exit"] \
                    and not (p["trend_guard"] and up_trend):
                pos, stop, short_sig = -1, short_sig[1], None
            out[t] = pos
        return pd.Series(out, index=df.index)


class _PatternStrategy(Strategy):
    """Base for pivot-pattern strategies: entry on a neckline break, structural stop, R-multiple target."""

    def _run(self, df: pd.DataFrame, detect: Any) -> pd.Series:
        k = int(self.params["pivot"])
        h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        atr = ind.atr(df).to_numpy(float)
        n = len(df)
        out = np.zeros(n)
        zz: list[tuple[str, int, float]] = []
        pos, stop, target = 0, 0.0, 0.0
        for t in range(n):
            pv = _confirmed_pivot(h, lo, t, k)
            if pv:
                _zigzag_add(zz, pv)
            if pos > 0 and (c[t] <= stop or c[t] >= target):
                pos = 0
            elif pos < 0 and (c[t] >= stop or c[t] <= target):
                pos = 0
            a = atr[t]
            if pos == 0 and t > 0 and np.isfinite(a) and a > 0 and len(zz) >= 3:
                sig = detect(zz, h, lo, c, t, a)
                if sig:
                    pos, stop, target = sig
            out[t] = pos
        return pd.Series(out, index=df.index)


class DoubleTopBottom(_PatternStrategy):
    name = "double_top_bottom"
    description = ("W / M patterns (Simon Pullen, The Trading Cafe): an impulse leg, a pullback of at most `max_pb` "
                   "of it, then a retest of the extreme within `tol` x impulse. Enter when price closes through the "
                   "neckline; stop beyond the extremes; target `rr` x risk, which must sit inside the impulse "
                   "range. 7 to `max_len` bars from first extreme to break.")
    defaults = {"pivot": 3, "max_pb": 0.5, "tol": 0.1, "rr": 1.0, "max_len": 30}
    grid = {"pivot": [2, 3], "max_pb": [0.45, 0.5], "tol": [0.1, 0.2], "rr": [1.0, 2.0]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["pivot"] >= 1 and 0 < p["max_pb"] < 1 and 0 < p["tol"] < 1 and p["rr"] > 0 and p["max_len"] >= 7

    def warmup(self) -> int:
        return 40

    def targets(self, df: pd.DataFrame) -> pd.Series:
        p = self.params

        def detect(zz, h, lo, c, t, a):  # noqa: ANN001, ANN202
            # the retest extreme may already be a confirmed swing: then the pattern is the 3 swings before it
            tail = zz[-4:-1] if len(zz) >= 4 and zz[-1][0] == zz[-3][0] and zz[-4][0] == zz[-2][0] else zz[-3:]
            (k0, i0, s), (k1, i1, x1), (k2, i2, neck) = tail
            if t - i1 < 7 or t - i1 > p["max_len"]:
                return None
            if k0 == "H" and k1 == "L" and k2 == "H":  # W: high -> low -> neckline high, then retest the low
                impulse = s - x1
                x2 = lo[i2 + 1: t + 1].min() if t > i2 else np.inf
                if impulse <= 0 or not (neck - x1 <= p["max_pb"] * impulse) or abs(x2 - x1) > p["tol"] * impulse:
                    return None
                if c[t] > neck >= c[t - 1]:
                    st = min(x1, x2) - 0.25 * a
                    tgt = c[t] + p["rr"] * (c[t] - st)
                    return (1, st, tgt) if tgt <= s else None
            if k0 == "L" and k1 == "H" and k2 == "L":  # M: low -> high -> neckline low, then retest the high
                impulse = x1 - s
                x2 = h[i2 + 1: t + 1].max() if t > i2 else -np.inf
                if impulse <= 0 or not (x1 - neck <= p["max_pb"] * impulse) or abs(x2 - x1) > p["tol"] * impulse:
                    return None
                if c[t] < neck <= c[t - 1]:
                    st = max(x1, x2) + 0.25 * a
                    tgt = c[t] - p["rr"] * (st - c[t])
                    return (-1, st, tgt) if tgt >= s else None
            return None

        return self._run(df, detect)


class HeadShoulders(_PatternStrategy):
    name = "head_shoulders"
    description = ("Head & shoulders (The Trading Cafe): inverse H&S = shoulder low, head clearly lower (by `head_min` "
                   "of its depth), a right shoulder within `sym` of the left. Enter when price closes through the "
                   "(sloped) neckline; stop beyond the right shoulder; target the measured move (head to "
                   "neckline, projected from the break). Regular H&S mirrors for shorts.")
    defaults = {"pivot": 3, "sym": 0.35, "head_min": 0.15, "max_len": 80}
    grid = {"pivot": [2, 3, 5], "sym": [0.25, 0.5], "head_min": [0.1, 0.2]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["pivot"] >= 1 and 0 < p["sym"] < 1 and 0 < p["head_min"] < 1 and p["max_len"] >= 10

    def warmup(self) -> int:
        return 40

    def targets(self, df: pd.DataFrame) -> pd.Series:
        p = self.params

        def detect(zz, h, lo, c, t, a):  # noqa: ANN001, ANN202
            if len(zz) < 4:
                return None
            # the right shoulder may already be a confirmed swing: then use the 4 swings before it
            four = zz[-5:-1] if len(zz) >= 5 and zz[-1][0] == zz[-5][0] else zz[-4:]
            (k_ls, i_ls, ls), (_, i_p1, p1), (_, i_hd, hd), (_, i_p2, p2) = four
            if t - i_ls > p["max_len"] or t <= i_p2 or i_p2 == i_p1:
                return None
            slope = (p2 - p1) / (i_p2 - i_p1)
            neck_t, neck_prev, neck_hd = p1 + slope * (t - i_p1), p1 + slope * (t - 1 - i_p1), p1 + slope * (i_hd - i_p1)
            if k_ls == "L":  # inverse H&S -> long
                rs = lo[i_p2 + 1: t + 1].min()
                depth = neck_hd - hd
                if depth <= 0 or ls - hd < p["head_min"] * depth or rs - hd < p["head_min"] * depth:
                    return None
                if abs(rs - ls) > p["sym"] * depth or not (c[t] > neck_t and c[t - 1] <= neck_prev):
                    return None
                return (1, rs - 0.25 * a, neck_t + depth)
            # regular H&S -> short
            rs = h[i_p2 + 1: t + 1].max()
            depth = hd - neck_hd
            if depth <= 0 or hd - ls < p["head_min"] * depth or hd - rs < p["head_min"] * depth:
                return None
            if abs(rs - ls) > p["sym"] * depth or not (c[t] < neck_t and c[t - 1] >= neck_prev):
                return None
            return (-1, rs + 0.25 * a, neck_t - depth)

        return self._run(df, detect)


class SupplyDemand(Strategy):
    name = "supply_demand"
    description = ("Supply & demand zones (Alex Morris, The Trading Cafe): a demand zone is the last bearish candle "
                   "before an impulsive move (>= `impulse_atr` ATR) that breaks the `lookback`-bar high. Trade only "
                   "the first two touches: enter on a rejection candle in the zone, stop below the zone, target "
                   "`rr` x risk. A close through the zone deletes it. Supply mirrors for shorts. trend=1 trades "
                   "only with the 200-SMA slope.")
    defaults = {"lookback": 20, "impulse_atr": 2.0, "rr": 2.0, "trend": 1}
    grid = {"lookback": [20, 50], "impulse_atr": [2.0, 3.0], "rr": [2.0, 3.0], "trend": [0, 1]}

    @classmethod
    def valid(cls, p: dict[str, Any]) -> bool:
        return p["lookback"] >= 5 and p["impulse_atr"] > 0 and p["rr"] > 0 and p["trend"] in (0, 1)

    def warmup(self) -> int:
        return max(self.params["lookback"] + 20, 40)

    def targets(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr = ind.atr(df).to_numpy(float)
        sma = ind.sma(df["close"], 200).to_numpy(float)
        hh = pd.Series(h).rolling(p["lookback"]).max().shift(1).to_numpy()
        ll = pd.Series(lo).rolling(p["lookback"]).min().shift(1).to_numpy()
        n = len(df)
        out = np.zeros(n)
        demand: list[list[float]] = []  # [zone_lo, zone_hi, touches]
        supply: list[list[float]] = []
        pos, stop, target = 0, 0.0, 0.0
        for t in range(1, n):
            a = atr[t]
            if not (np.isfinite(a) and a > 0 and np.isfinite(hh[t]) and np.isfinite(ll[t])):
                continue
            if pos > 0 and (c[t] <= stop or c[t] >= target):
                pos = 0
            elif pos < 0 and (c[t] >= stop or c[t] <= target):
                pos = 0
            rising = np.isfinite(sma[t]) and sma[t] > sma[max(0, t - 20)]
            falling = np.isfinite(sma[t]) and sma[t] < sma[max(0, t - 20)]
            rng, mid = h[t] - lo[t], (h[t] + lo[t]) / 2
            # touches and entries on existing zones (before creating new ones from this bar)
            for z in list(demand):
                if c[t] < z[0]:
                    demand.remove(z)  # broken
                elif lo[t] <= z[1]:
                    z[2] += 1
                    if z[2] > 2:
                        demand.remove(z)
                    elif pos <= 0 and rng > 0 and c[t] > z[1] and c[t] > mid and (not p["trend"] or rising):
                        st = z[0] - 0.25 * a  # rejection: dipped into the zone, closed back above it, upper half
                        pos, stop, target = 1, st, c[t] + p["rr"] * (c[t] - st)
                        demand.remove(z)
            for z in list(supply):
                if c[t] > z[1]:
                    supply.remove(z)
                elif h[t] >= z[0]:
                    z[2] += 1
                    if z[2] > 2:
                        supply.remove(z)
                    elif pos >= 0 and rng > 0 and c[t] < z[0] and c[t] < mid and (not p["trend"] or falling):
                        st = z[1] + 0.25 * a
                        pos, stop, target = -1, st, c[t] - p["rr"] * (st - c[t])
                        supply.remove(z)
            # new zones: an impulsive close beyond the recent range, from the last opposite candle (base)
            if c[t] > hh[t]:
                b = next((j for j in range(t - 1, max(t - 6, 0), -1) if c[j] < o[j]), None)
                if b is not None and c[t] - lo[b] >= p["impulse_atr"] * a:
                    demand.append([lo[b], h[b], 0])
                    del demand[:-5]
            if c[t] < ll[t]:
                b = next((j for j in range(t - 1, max(t - 6, 0), -1) if c[j] > o[j]), None)
                if b is not None and h[b] - c[t] >= p["impulse_atr"] * a:
                    supply.append([lo[b], h[b], 0])
                    del supply[:-5]
            out[t] = pos
        return pd.Series(out, index=df.index)


BUILTINS: list[type[Strategy]] = [SMACross, EMACross, RSIReversion, DonchianBreakout, BollingerReversion, TrendFilteredRSI,
                                  FibRetracement, MarketStructure, FlowReversal, SIDMethod, DoubleTopBottom, HeadShoulders,
                                  SupplyDemand]
