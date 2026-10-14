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
- flow    (order flow):   a long fails while a bearish CVD divergence is active (a short: bullish).
          Needs taker volume (Binance / synthetic / CSV with taker_buy); passes when there is none.
- vol / events: volatility regime (act: reduce size) and macro / per-symbol (@AAPL earnings) blackouts.
- htf_bias (top-down):    a long fails against the weekly structure (or its 3-week momentum when the
          week is ranging), or against the daily structure when the weekly picture is mixed.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from . import indicators as ind
from .backtest import timeframe_seconds
from .context import describe_level, htf_bias, key_levels, nearest_levels, p_touch, sigma_per_bar, stretch_z, to_daily

FILTER_NAMES = ("levels", "stretch", "flow", "vol", "events", "htf_bias")
log = logging.getLogger("hermes_trader.filters")


@dataclass
class FilterResult:
    name: str
    passed: bool
    value: float | None
    note: str
    mult: float = 0.0  # in act mode a failing filter scales size by this; 0 = skip the entry


_TZ_ABBREV = {"EST", "EDT", "CST", "CDT", "MST", "MDT", "PST", "PDT", "ET", "CT", "PT", "BST", "CET", "CEST",
              "AEST", "AEDT", "AWST", "JST", "IST", "HKT", "SGT"}


def parse_events(items: list[Any]) -> tuple[list[tuple[datetime, str]], list[str]]:
    """'2026-10-28 14:00 America/New_York FOMC' | '2026-11-10T13:30Z CPI' -> ([(utc time, label)], errors).

    Zones must be IANA names (America/New_York) or UTC/Z: abbreviations like EST are ambiguous across
    daylight saving, so they are rejected rather than guessed. A bad line is reported and skipped.
    """
    from zoneinfo import ZoneInfo

    out, errors = [], []
    for raw in items or []:
        parts = str(raw).split()
        if not parts:
            continue
        try:
            if "T" in parts[0]:
                when, rest = parts[0].replace("Z", "+00:00").replace("z", "+00:00"), parts[1:]
            else:
                when, rest = f"{parts[0]}T{parts[1] if len(parts) > 1 else '00:00'}", parts[2:]
            tz = "UTC"
            if rest and ("/" in rest[0] or rest[0].upper() in ("UTC", "Z", "GMT")):
                tz, rest = ("UTC" if rest[0].upper() in ("UTC", "Z", "GMT") else rest[0]), rest[1:]
            elif rest and rest[0].upper().strip(",") in _TZ_ABBREV:
                raise ValueError(f"time zone '{rest[0]}' is ambiguous; use an IANA name such as America/New_York")
            dt = datetime.fromisoformat(when)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(tz))
            out.append((dt.astimezone(ZoneInfo("UTC")), " ".join(rest) or "event"))
        except (ValueError, KeyError) as e:
            errors.append(f"skipped event {raw!r}: {e}. Format: 'YYYY-MM-DD HH:MM Area/City Name'")
    return sorted(out), errors


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
        self.events, self.event_errors = parse_events(self.sub("events").get("dates") or [])
        for err in self.event_errors:
            log.warning(err)
        self.iv: Any = None  # vol.ImpliedVol, attached by the runtime when vol.iv is on

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
                 daily: pd.DataFrame, symbol: str = "", now: datetime | None = None,
                 implied: tuple[float, float, str] | None = None) -> list[FilterResult]:
        out = []
        if self.enabled("levels"):
            out.append(self.check_levels(side, price, df, atr, daily, now))
        if self.enabled("stretch"):
            out.append(self.check_stretch(side, df))
        if self.enabled("flow"):
            out.append(self.check_flow(side, df))
        if self.enabled("vol"):
            out.append(self.check_vol(df, symbol, implied))
        if self.enabled("events"):
            out.append(self.check_events(now or df.index[-1].to_pydatetime(), symbol))
        if self.enabled("htf_bias"):
            out.append(self.check_htf_bias(side, daily, now if now is not None else df.index[-1]))
        return out

    def check_htf_bias(self, side: int, daily: pd.DataFrame, now: Any) -> FilterResult:
        """Trade with the weekly structure (or its recent momentum when ranging); daily confirms."""
        b = htf_bias(daily, now, int(self.sub("htf_bias").get("momentum_weeks", 3)))
        word = {1: "up", -1: "down", 0: "mixed"}
        note = (f"weekly {word[b['weekly']]}" + ("" if b["weekly"] else f" (3-week momentum {word[b['momentum']]})")
                + f", daily {word[b['daily']]}")
        against = b["bias"] * side < 0 or (b["bias"] == 0 and b["daily"] * side < 0)
        if not b["bias"] and not b["daily"] and self.sub("htf_bias").get("skip_without_bias", False):
            return FilterResult("htf_bias", False, 0.0, note + "; no clear bias")
        return FilterResult("htf_bias", not against, float(b["bias"]), note + ("; against the trend" if against else ""))

    def implied_vol(self, symbol: str) -> tuple[float, float, str] | None:
        if self.iv is None or not self.sub("vol").get("iv", True):
            return None
        try:
            return self.iv.for_symbol(symbol)
        except Exception:  # noqa: BLE001
            return None

    def check_levels(self, side: int, price: float, df: pd.DataFrame, atr: float | None,
                     daily: pd.DataFrame, now: datetime | None = None) -> FilterResult:
        lc = self.sub("levels")
        atr = _finite(atr)
        if not atr or not (price > 0):
            return FilterResult("levels", True, None, "no ATR yet")
        lv = key_levels(daily, price, int(lc.get("pivot", 3)), bool(lc.get("round_numbers", True)),
                        now=now if now is not None else df.index[-1])
        # the level in front counts however close it is: buying just under resistance has ~no room
        sup, res = nearest_levels(lv, price, 0.0)
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


    def check_flow(self, side: int, df: pd.DataFrame) -> FilterResult:
        fc = self.sub("flow")
        n = int(fc.get("bars", 24))
        if not ind.has_flow(df, min(len(df), 50)):
            return FilterResult("flow", True, None, "no order-flow data on this venue")
        if len(df) < 2 * n:
            return FilterResult("flow", True, None, "not enough bars for order flow yet")
        code = int(ind.cvd_divergence(df, n).iloc[-1])
        share = float(ind.delta_share(df, n).iloc[-1])
        against = code * side < 0
        note = f"net aggression {share:+.0%} over {n} bars" + (f"; {ind.CVD_DIVERGENCE[code]}" if code else "")
        return FilterResult("flow", not against, round(share, 4), note)


    def check_vol(self, df: pd.DataFrame, symbol: str = "",
                  implied: tuple[float, float, str] | None = None) -> FilterResult:
        """Volatility regime: realised vol exploding vs its normal, or implied vol jumping vs its own norm."""
        from .backtest import periods_per_year
        from .brokers.base import asset_class_of

        vc = self.sub("vol")
        short, long_ = int(vc.get("short_bars", 24)), int(vc.get("long_bars", 720))
        r = np.log(df["close"]).diff().dropna()
        if len(r) < max(short * 3, 100):
            return FilterResult("vol", True, None, "not enough history")
        ppy = periods_per_year(self.tf, asset_class_of(symbol).value if symbol else "crypto")
        rv_s = float(r.tail(short).std(ddof=1) * math.sqrt(ppy))
        rv_l = float(r.tail(long_).std(ddof=1) * math.sqrt(ppy))
        if not rv_l > 0:
            return FilterResult("vol", True, None, "no volatility")
        exp = rv_s / rv_l
        parts = [f"realised vol {rv_s:.0%} over {short} bars vs {rv_l:.0%} normal (x{exp:.1f})"]
        stressed = exp > float(vc.get("max_expansion", 2.0))
        if implied and implied[1] > 0:
            iv, base, src = implied
            jump = iv / base
            parts.append(f"{src} {iv:.0f}% vs {base:.0f}% 30-day median (x{jump:.2f})")
            stressed = stressed or jump > float(vc.get("max_iv_jump", 1.3))
        note = "; ".join(parts) + ("; stressed: trade smaller" if stressed else "")
        return FilterResult("vol", not stressed, round(exp, 3), note, mult=float(vc.get("reduce_to", 0.5)))

    @staticmethod
    def _event_symbols(label: str) -> set[str]:
        return {tok[1:].upper() for tok in label.split() if tok.startswith("@") and len(tok) > 1}

    @staticmethod
    def _applies(tags: set[str], symbol: str) -> bool:
        if not tags:
            return True  # market-wide (FOMC, CPI)
        sym = symbol.upper()
        return sym in tags or sym.split("/")[0] in tags

    def check_events(self, now: datetime, symbol: str = "") -> FilterResult:
        """Market-wide events: ±minutes. Events tagged @SYMBOL (e.g. earnings): days before / after."""
        ec = self.sub("events")
        windows = {
            False: (pd.Timedelta(minutes=int(ec.get("before_minutes", 60))),
                    pd.Timedelta(minutes=int(ec.get("after_minutes", 60)))),
            True: (pd.Timedelta(days=float(ec.get("symbol_before_days", 14))),
                   pd.Timedelta(days=float(ec.get("symbol_after_days", 1)))),
        }
        ts = pd.Timestamp(now)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        upcoming = []
        for when, label in self.events:
            tags = self._event_symbols(label)
            if not self._applies(tags, symbol):
                continue
            before, after = windows[bool(tags)]
            w = pd.Timestamp(when)
            if w - before <= ts <= w + after:
                mins = int((w - ts).total_seconds() // 60)
                rel = (f"in {mins} min" if mins > 0 else f"{-mins} min ago") if abs(mins) < 2880 else \
                      (f"in {mins / 1440:.0f} days" if mins > 0 else f"{-mins / 1440:.0f} days ago")
                return FilterResult("events", False, float(mins), f"{label} {rel} (blackout window)",
                                    mult=0.5 if ec.get("action", "skip") == "reduce" else 0.0)
            if w > ts:
                upcoming.append((w, label))
        nxt = min(upcoming) if upcoming else None
        return FilterResult("events", True, None, f"next event: {nxt[1]} {nxt[0]:%Y-%m-%d %H:%M}Z" if nxt
                            else "no upcoming events listed")


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
                     daily: pd.DataFrame | None = None, details: bool = False, symbol: str = "") -> dict[str, Any]:
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
    per: dict[str, dict[str, list[tuple[float, float | None, float]]]] = {
        n: {"blocked": [], "passed": []} for n in filters.names()}
    step = pd.Timedelta(seconds=timeframe_seconds(filters.tf))
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
        # live decisions happen when bar i closes, i.e. at its open time + one bar
        verdicts = filters.evaluate(side, float(close[i]), hist, atr[i], d, symbol=symbol,
                                    now=(df.index[i] + step).to_pydatetime())
        for r in verdicts:
            per[r.name]["passed" if r.passed else "blocked"].append((trade, fwd, max(0.0, r.mult)))
        if details:
            rows.append({"ts": str(df.index[i]), "side": side, "trade_pct": round(trade * 100, 3),
                         **{r.name: {"passed": r.passed, "value": r.value, "note": r.note} for r in verdicts}})
    out: dict[str, Any] = {"entries": entries, "horizon_bars": horizon, "filters": {}}
    for name, g in per.items():
        def stats(xs: list[tuple[float, float | None, float]]) -> dict[str, Any]:
            tr = [a for a, _, _ in xs]
            fw = [b for _, b, _ in xs if b is not None]
            return {"n": len(xs), "avg_trade_pct": _avg(tr), "win_rate": round(float(np.mean([a > 0 for a in tr])), 3)
                    if tr else None, "avg_fwd_pct": _avg(fw)}
        b, p = stats(g["blocked"]), stats(g["passed"])
        bt, pt = [a for a, _, _ in g["blocked"]], [a for a, _, _ in g["passed"]]
        kept_of_blocked = [a * m for a, _, m in g["blocked"]]  # a "reduce" filter keeps part of the trade
        out["filters"][name] = {
            "blocked": b, "passed": p,
            "pnl_if_acting_pct": round(float(np.sum(pt) + np.sum(kept_of_blocked)) * 100, 3),
            "pnl_without_pct": round((float(np.sum(pt + bt)) if pt or bt else 0.0) * 100, 3),
            "verdict": _verdict(bt, pt, 10),
        }
    if details:
        out["entries_detail"] = rows
    return out
