"""Market context shared by entry filters, the LLM/JEV facts and the desktop chart.

- Key levels (price action): daily and weekly swing highs/lows, previous day/week high and low,
  and round "psychological" numbers, merged into zones.
- Volatility maths (Black-Scholes-Merton, zero drift): expected move over a horizon, the chance of
  touching or finishing beyond a price, and how stretched the latest move is in sigma units.

Everything here only reads the bars it is given, so it is safe in backtests as long as callers
pass history up to the decision bar.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from . import indicators as ind

# ---- probability helpers (BSM with r = q = 0: a driftless log-normal walk) -----------------------


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def sigma_per_bar(df: pd.DataFrame, n: int = 100) -> float | None:
    """Standard deviation of log returns over the last n closed bars."""
    r = np.log(df["close"]).diff().dropna().tail(n)
    if len(r) < 20:
        return None
    s = float(r.std(ddof=1))
    return s if s > 0 and math.isfinite(s) else None


def horizon_sigma(sigma_bar: float, bars: float) -> float:
    return sigma_bar * math.sqrt(max(bars, 1e-9))


def expected_move(price: float, sigma_bar: float, bars: float) -> dict[str, Any]:
    """±1σ / ±2σ price bands after `bars` bars (log-normal, zero drift)."""
    s = horizon_sigma(sigma_bar, bars)
    return {"bars": bars, "sigma_pct": round(s * 100, 3),
            "band_1s": [price * math.exp(-s), price * math.exp(s)],
            "band_2s": [price * math.exp(-2 * s), price * math.exp(2 * s)]}


def p_finish_beyond(price: float, level: float, sigma_bar: float, bars: float) -> float:
    """BSM N(d2) with r=0: chance the price ends the horizon beyond `level` (above if level > price)."""
    s = horizon_sigma(sigma_bar, bars)
    if s <= 0:
        return 0.0
    d2 = (math.log(price / level) - 0.5 * s * s) / s
    return norm_cdf(d2) if level >= price else 1.0 - norm_cdf(d2)


def p_touch(price: float, level: float, sigma_bar: float, bars: float) -> float:
    """Reflection principle: chance the price trades at `level` at some point within the horizon."""
    s = horizon_sigma(sigma_bar, bars)
    if s <= 0:
        return 0.0
    return min(1.0, 2.0 * (1.0 - norm_cdf(abs(math.log(level / price)) / s)))


def stretch_z(df: pd.DataFrame, bars: int, sigma_bar: float) -> float | None:
    """The last `bars`-bar log return measured in sigmas: +2.5 = an unusually extended rally."""
    c = df["close"]
    if len(c) <= bars or sigma_bar <= 0:
        return None
    return float(math.log(c.iloc[-1] / c.iloc[-1 - bars]) / horizon_sigma(sigma_bar, bars))


# ---- key levels ------------------------------------------------------------------------------


def to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Resample intraday bars to daily candles (fallback when the venue's daily bars aren't available)."""
    if df.empty:
        return df
    d = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return d.dropna(subset=["close"])


def pivots(df: pd.DataFrame, k: int) -> tuple[list[float], list[float]]:
    """Confirmed swing highs/lows: a bar whose high (low) is the extreme of k bars on each side.

    Only bars with k complete bars after them qualify, so a pivot never depends on unseen data.
    """
    h, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    highs, lows = [], []
    for i in range(k, len(df) - k):  # strictly beyond the k bars before, at least level with the k after
        if h[i] > h[i - k: i].max() and h[i] >= h[i + 1: i + k + 1].max():
            highs.append(float(h[i]))
        if lo[i] < lo[i - k: i].min() and lo[i] <= lo[i + 1: i + k + 1].min():
            lows.append(float(lo[i]))
    return highs, lows


def round_step(price: float) -> float:
    """Spacing of 'psychological' numbers: 60,000 -> 5,000; 3,000 -> 500; 150 -> 50; 0.62 -> 0.05."""
    return 10 ** math.floor(math.log10(price)) / 2 if price > 0 else 0.0


def key_levels(daily: pd.DataFrame, price: float, pivot: int = 3, round_numbers: bool = True,
               merge_frac: float = 0.25, max_dist: float = 0.25) -> list[dict[str, Any]]:
    """Support/resistance zones near `price` from daily bars (most recent bar may be in progress).

    Returns [{price, kinds, strength}] sorted by price, within ±max_dist (fraction) of price.
    Zones closer than merge_frac x daily ATR are merged; strength = how many sources agree.
    """
    if daily.empty or price <= 0:
        return []
    raw: list[tuple[float, str]] = []
    done = daily.iloc[:-1] if len(daily) > 1 else daily  # completed days
    hs, ls = pivots(done, pivot)
    raw += [(x, "daily swing high") for x in hs] + [(x, "daily swing low") for x in ls]
    if len(done) >= 1:
        raw += [(float(done["high"].iloc[-1]), "prev day high"), (float(done["low"].iloc[-1]), "prev day low")]
    weekly = done.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(weekly) >= 2:
        whs, wls = pivots(weekly, 2)
        raw += [(x, "weekly swing high") for x in whs] + [(x, "weekly swing low") for x in wls]
        prev = weekly.iloc[-2]
        raw += [(float(prev["high"]), "prev week high"), (float(prev["low"]), "prev week low")]
    if round_numbers:
        step = round_step(price)
        base = math.floor(price / step) * step
        raw += [(base + i * step, "round number") for i in range(-3, 5) if base + i * step > 0]
    raw = [(p, k) for p, k in raw if abs(p / price - 1) <= max_dist]
    if not raw:
        return []
    a = ind.atr(done, 14).iloc[-1] if len(done) > 15 else np.nan
    gap = (float(a) if math.isfinite(a) else price * 0.01) * merge_frac
    raw.sort()
    zones: list[dict[str, Any]] = []
    for p, k in raw:
        if zones and p - zones[-1]["_hi"] <= gap:
            z = zones[-1]
            z["_ps"].append(p)
            z["_hi"] = p
            if k not in z["kinds"]:
                z["kinds"].append(k)
        else:
            zones.append({"_ps": [p], "_hi": p, "kinds": [k]})
    return [{"price": float(np.mean(z["_ps"])), "kinds": z["kinds"], "strength": len(z["_ps"])} for z in zones]


def nearest_levels(levels: list[dict[str, Any]], price: float, min_gap: float = 0.0
                   ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(nearest support below, nearest resistance above), ignoring zones within min_gap of price."""
    below = [z for z in levels if z["price"] < price - min_gap]
    above = [z for z in levels if z["price"] > price + min_gap]
    return (max(below, key=lambda z: z["price"]) if below else None,
            min(above, key=lambda z: z["price"]) if above else None)


def describe_level(z: dict[str, Any] | None) -> str:
    if not z:
        return "none nearby"
    return f"{z['price']:.6g} ({', '.join(z['kinds'][:3])})"


def price_context(df: pd.DataFrame, daily: pd.DataFrame | None, horizon_bars: int = 24,
                  pivot: int = 3, round_numbers: bool = True) -> dict[str, Any]:
    """Compact facts for the LLM / JEV / chart: levels, expected move, stretch, touch odds."""
    price = float(df["close"].iloc[-1])
    s = sigma_per_bar(df)
    out: dict[str, Any] = {"price": price}
    if s:
        out["expected_move"] = expected_move(price, s, horizon_bars)
        out["stretch_z_24"] = round(z, 2) if (z := stretch_z(df, min(24, len(df) - 1), s)) is not None else None
    lv = key_levels(daily if daily is not None else to_daily(df), price, pivot, round_numbers)
    a = float(ind.atr(df).iloc[-1]) if len(df) > 15 else float("nan")
    sup, res = nearest_levels(lv, price, a * 0.25 if math.isfinite(a) else 0.0)
    out["levels"] = [{"price": round(z["price"], 8), "kinds": z["kinds"], "strength": z["strength"]} for z in lv]
    out["nearest_support"] = describe_level(sup)
    out["nearest_resistance"] = describe_level(res)
    out["support_dist_pct"] = round((sup["price"] / price - 1) * 100, 3) if sup else None
    out["resistance_dist_pct"] = round((res["price"] / price - 1) * 100, 3) if res else None
    if ind.has_flow(df) and len(df) > 50:
        code = int(ind.cvd_divergence(df, 24).iloc[-1])
        last = int(ind.candle_delta_divergence(df).iloc[-1])
        out["order_flow"] = {
            "net_aggression_24b": round(float(ind.delta_share(df, 24).iloc[-1]), 4),
            "net_aggression_last_bar": round(float(ind.delta_share(df, 1).iloc[-1]), 4),
            "cvd_divergence": ind.CVD_DIVERGENCE.get(code, "none"),
            "last_bar": {1: "green bar despite net selling (sellers absorbed)",
                         -1: "red bar despite net buying (buyers absorbed)"}.get(last, "delta agrees with the bar"),
        }
    if s:
        for name, z in (("support", sup), ("resistance", res)):
            if z:
                out[f"p_touch_{name}_{horizon_bars}b"] = round(p_touch(price, z["price"], s, horizon_bars), 3)
    return out
