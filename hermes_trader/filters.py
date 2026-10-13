"""Deterministic entry filters, shadow first.

Every new-risk entry is checked by each enabled filter. In ``shadow`` mode a filter only records what
it *would* have done; in ``act`` mode a failing filter skips the entry. Exits are never touched.
Each check is scored afterwards (the move over ``horizon_bars`` in the trade's direction) so
``hermes-trader filters`` can show whether entries a filter would block really did worse. For
instant evidence, ``evaluate_history`` replays a strategy over past bars with the same filters.

Filters
- levels  (price action): enough room to the next key level? reward/risk = distance to the nearest
          support/resistance zone in the trade's direction / ATR-stop distance. Fails below min_rr.
- stretch (BSM sigma):    don't chase. The last N-bar move in sigma units; a long fails above +max_z,
          a short below -max_z.
More filters (order flow, volatility regime, event blackout) plug in the same way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from . import indicators as ind
from .backtest import timeframe_seconds
from .context import describe_level, key_levels, nearest_levels, p_touch, sigma_per_bar, stretch_z, to_daily

FILTER_NAMES = ("levels", "stretch")


@dataclass
class FilterResult:
    name: str
    passed: bool
    value: float | None
    note: str


def _finite(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class EntryFilters:
    def __init__(self, cfg: dict[str, Any], risk_cfg: dict[str, Any], broker: Any = None,
                 timeframe: str = "1h") -> None:
        self.c = cfg
        self.risk = risk_cfg
        self.broker = broker
        self.tf = timeframe
        self._daily: dict[str, tuple[str, pd.DataFrame]] = {}

    # ---- config ------------------------------------------------------------------------------
    def sub(self, name: str) -> dict[str, Any]:
        return self.c.get(name) or {}

    def enabled(self, name: str) -> bool:
        return bool(self.sub(name).get("enabled", True))

    def mode(self, name: str) -> str:
        return str(self.sub(name).get("mode") or self.c.get("mode", "shadow"))

    def names(self) -> list[str]:
        return [n for n in FILTER_NAMES if self.enabled(n)]

    # ---- data --------------------------------------------------------------------------------
    def daily(self, symbol: str, df: pd.DataFrame, now: datetime) -> pd.DataFrame:
        """Venue daily bars (cached per symbol per day); resampled intraday bars as a fallback."""
        key = now.date().isoformat()
        hit = self._daily.get(symbol)
        if hit and hit[0] == key:
            return hit[1]
        d = None
        days = int(self.sub("levels").get("lookback", 180))
        if self.broker is not None:
            try:
                if self._synthetic():  # synthetic daily bars are a separate series: derive them instead
                    n = min(int(days * 86400 / timeframe_seconds(self.tf)), 6000)
                    d = to_daily(self.broker.fetch_ohlcv(symbol, self.tf, n))
                else:
                    d = self.broker.fetch_ohlcv(symbol, "1d", days)
            except Exception:  # noqa: BLE001 - CSV sources etc. may have no daily file
                d = None
        if d is None or len(d) < 10:
            d = to_daily(df)
        self._daily[symbol] = (key, d)
        return d

    def _synthetic(self) -> bool:
        from .data import SyntheticData

        return isinstance(getattr(self.broker, "data", None), SyntheticData)

    # ---- checks ------------------------------------------------------------------------------
    def evaluate(self, side: int, price: float, df: pd.DataFrame, atr: float | None,
                 daily: pd.DataFrame) -> list[FilterResult]:
        out = []
        if self.enabled("levels"):
            out.append(self.check_levels(side, price, df, atr, daily))
        if self.enabled("stretch"):
            out.append(self.check_stretch(side, df))
        return out

    def check_levels(self, side: int, price: float, df: pd.DataFrame, atr: float | None,
                     daily: pd.DataFrame) -> FilterResult:
        lc = self.sub("levels")
        atr = _finite(atr)
        if not atr:
            return FilterResult("levels", True, None, "no ATR yet")
        lv = key_levels(daily, price, int(lc.get("pivot", 3)), bool(lc.get("round_numbers", True)))
        sup, res = nearest_levels(lv, price, 0.25 * atr)
        target = res if side > 0 else sup
        if target is None:
            return FilterResult("levels", True, None, "open air: no key level in the way")
        stop = float(self.risk.get("atr_stop_mult", 2.0)) * atr
        rr = abs(target["price"] - price) / stop
        h = int(self.c.get("horizon_bars", 12))
        s = sigma_per_bar(df)
        reach = f", {p_touch(price, target['price'], s, h):.0%} chance to touch in {h} bars" if s else ""
        word = "resistance" if side > 0 else "support"
        return FilterResult("levels", rr >= float(lc.get("min_rr", 1.5)), round(rr, 3),
                            f"room {rr:.1f}R to {word} {describe_level(target)}{reach}")

    def check_stretch(self, side: int, df: pd.DataFrame) -> FilterResult:
        sc = self.sub("stretch")
        bars = int(sc.get("bars", 24))
        s = sigma_per_bar(df, int(sc.get("vol_bars", 100)))
        z = stretch_z(df, bars, s) if s else None
        if z is None:
            return FilterResult("stretch", True, None, "not enough history")
        limit = float(sc.get("max_z", 2.0))
        chasing = side * z > limit
        return FilterResult("stretch", not chasing, round(z, 3),
                            f"last {bars} bars moved {z:+.1f}σ" + (f" (beyond ±{limit:g}σ: chasing)" if chasing else ""))


# ---- reports -------------------------------------------------------------------------------------


def _avg(xs: list[float]) -> float | None:
    return round(float(np.mean(xs)) * 100, 3) if xs else None


def _verdict(blocked: list[float], passed: list[float], min_n: int) -> str:
    if len(blocked) < min_n:
        return f"Keep shadowing: {len(blocked)} would-be blocks scored, need {min_n}."
    b, p = float(np.mean(blocked)), float(np.mean(passed)) if passed else 0.0
    if b < 0 and b < p - 0.001:
        return (f"Edge: entries it would block averaged {b * 100:+.2f}% vs {p * 100:+.2f}% for the rest. "
                "Consider mode: act for this filter.")
    return f"No edge yet: blocked {b * 100:+.2f}% vs passed {p * 100:+.2f}%. Keep it in shadow (or disable)."


def filter_report(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Live shadow/act stats from the journal: did would-be-blocked entries really do worse?"""
    min_n = int(cfg.get("min_resolved", 30))
    out: dict[str, Any] = {"mode": cfg.get("mode", "shadow"), "horizon_bars": cfg.get("horizon_bars", 12),
                           "filters": {}}
    for name in FILTER_NAMES:
        rs = [r for r in rows if r["name"] == name and not r.get("error")]
        done = [r for r in rs if r.get("resolved_ts") and r.get("fwd_ret") is not None]
        blocked = [r["fwd_ret"] for r in done if not r["passed"]]
        passed = [r["fwd_ret"] for r in done if r["passed"]]
        sub = cfg.get(name) or {}
        out["filters"][name] = {
            "enabled": bool(sub.get("enabled", True)), "mode": sub.get("mode") or cfg.get("mode", "shadow"),
            "checks": len(rs), "would_block": sum(1 for r in rs if not r["passed"]),
            "applied": sum(1 for r in rs if r.get("applied")), "scored": len(done),
            "avg_fwd_pct_blocked": _avg(blocked), "avg_fwd_pct_passed": _avg(passed),
            "recommendation": _verdict(blocked, passed, min_n),
        }
    return out


def evaluate_history(df: pd.DataFrame, targets: pd.Series, filters: EntryFilters, horizon: int,
                     daily: pd.DataFrame | None = None, details: bool = False) -> dict[str, Any]:
    """Replay a strategy's entries over history and split them by each filter's verdict.

    Entry = a bar where the target turns non-zero or flips side. Trade return runs from that bar's
    close until the target changes again; the horizon return is the move over `horizon` bars.
    Filters only see bars up to the entry bar (daily levels use completed days + the current day so far).
    """
    t = targets.fillna(0.0).clip(-1, 1).to_numpy()
    close = df["close"].to_numpy(float)
    sign = np.sign(t)
    atr = ind.atr(df).to_numpy(float)
    daily_full = daily if daily is not None else to_daily(df)
    per: dict[str, dict[str, list[tuple[float, float | None]]]] = {
        n: {"blocked": [], "passed": []} for n in filters.names()}
    entries = 0
    rows: list[dict[str, Any]] = []
    start = max(30, int(filters.sub("stretch").get("vol_bars", 100)))
    for i in range(start, len(t) - 1):
        if sign[i] == 0 or sign[i] == sign[i - 1]:
            continue
        side = int(sign[i])
        j = i + 1
        while j < len(t) and sign[j] == side:
            j += 1
        j = min(j, len(t) - 1)
        trade = side * (close[j] / close[i] - 1)
        fwd = side * (close[min(i + horizon, len(t) - 1)] / close[i] - 1) if i + horizon < len(t) else None
        hist = df.iloc[: i + 1]
        day = hist.index[-1].normalize()
        part = hist[hist.index >= day]
        d = pd.concat([daily_full[daily_full.index < day],
                       pd.DataFrame({"open": [part["open"].iloc[0]], "high": [part["high"].max()],
                                     "low": [part["low"].min()], "close": [part["close"].iloc[-1]],
                                     "volume": [part["volume"].sum()]}, index=[day])])
        entries += 1
        verdicts = filters.evaluate(side, float(close[i]), hist, atr[i], d)
        for r in verdicts:
            per[r.name]["passed" if r.passed else "blocked"].append((trade, fwd))
        if details:
            rows.append({"ts": str(df.index[i]), "side": side, "trade_pct": round(trade * 100, 3),
                         **{r.name: {"passed": r.passed, "value": r.value, "note": r.note} for r in verdicts}})
    out: dict[str, Any] = {"entries": entries, "horizon_bars": horizon, "filters": {}}
    for name, g in per.items():
        def stats(xs: list[tuple[float, float | None]]) -> dict[str, Any]:
            tr = [a for a, _ in xs]
            fw = [b for _, b in xs if b is not None]
            return {"n": len(xs), "avg_trade_pct": _avg(tr), "win_rate": round(float(np.mean([a > 0 for a in tr])), 3)
                    if tr else None, "avg_fwd_pct": _avg(fw)}
        b, p = stats(g["blocked"]), stats(g["passed"])
        bt, pt = [a for a, _ in g["blocked"]], [a for a, _ in g["passed"]]
        out["filters"][name] = {
            "blocked": b, "passed": p,
            "pnl_if_acting_pct": round((float(np.sum(pt)) if pt else 0.0) * 100, 3),
            "pnl_without_pct": round((float(np.sum(pt + bt)) if pt or bt else 0.0) * 100, 3),
            "verdict": _verdict(bt, pt, 10),
        }
    if details:
        out["entries_detail"] = rows
    return out
