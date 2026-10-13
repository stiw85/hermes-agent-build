"""TypeSafe Jev as a calibrated trade gate.

Jev is a non-generative decision model: send a text `state` plus typed questions, get back
calibrated probabilities (noul = P(yes), choice = distribution over options). It does no
arithmetic, so the bot computes every number first and Jev judges the situation.

Per proposed *entry* (an order that adds risk) Jev answers:
  worth_taking (noul)  - will this entry more likely reach profit than its ATR stop?
  regime       (choice)- trending_up / trending_down / ranging / volatile (logged for analysis)

Modes:
  shadow - score and journal every entry, change nothing. The report compares Jev's
           probabilities with what actually happened, so you can decide whether to trust it.
  gate   - p < veto_below -> veto, p < reduce_below -> half size. Can only shrink or veto,
           never enlarge, and exits are never sent to Jev.

Endpoints: TypeSafe direct (default) https://api.typesafe.ai/v1/systemone with TYPESAFE_API_KEY,
or OpenRouter https://openrouter.ai/api/alpha/decisions with OPENROUTER_API_KEY.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from .agent.tools import market_snapshot
from .brokers.base import asset_class_of
from .models import Account, Signal
from .risk import RiskDecision

REGIMES = {
    "trending_up": "Price is in a persistent uptrend: higher highs and lows, above its longer moving averages.",
    "trending_down": "Price is in a persistent downtrend: lower highs and lows, below its longer moving averages.",
    "ranging": "Price is moving sideways inside a range without a clear direction.",
    "volatile": "Price is swinging hard in both directions; moves are large relative to the trend.",
}

STRATEGY_STYLE = {
    "sma_cross": "trend-following (moving-average crossover)",
    "ema_cross": "trend-following (exponential moving-average crossover)",
    "donchian_breakout": "breakout (new N-bar high or low)",
    "rsi_reversion": "mean reversion (buy oversold / sell overbought RSI)",
    "bollinger_reversion": "mean reversion (fade moves outside Bollinger bands)",
    "trend_rsi": "buy-the-dip inside an uptrend",
    "market_structure": "price action (buy the retest after a break of structure; exit when structure breaks)",
    "fib_retracement": "pullback (buy a Fibonacci retracement of the last swing, or sell one in a down-swing)",
}


class JevError(RuntimeError):
    pass


class JevClient:
    def __init__(self, url: str, model: str, api_key: str | None, timeout: float = 20.0,
                 session: requests.Session | None = None) -> None:
        if not api_key:
            raise JevError("JEV API key missing")
        self.url = url
        self.model = model
        self.key = api_key
        self.timeout = timeout
        self.s = session or requests.Session()

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> JevClient:
        from .config import missing_secret_hint

        env = c.get("api_key_env", "TYPESAFE_API_KEY")
        key = (os.environ.get(env) or "").strip()
        if not key:
            raise JevError(f"JEV is enabled but its API key is missing: {missing_secret_hint(env)}")
        return cls(c["url"], c["model"], key, float(c.get("timeout", 20)))

    def decide(self, state: dict[str, Any] | str, questions: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "X-Title": "hermes-trader"}
        body: dict[str, Any] = {"model": self.model, "state": state, "questions": questions}
        last = ""
        for attempt in range(3):
            try:
                r = self.s.post(self.url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(0.5 * 2**attempt)
                continue
            if r.status_code == 400 and not isinstance(body["state"], str):
                body["state"] = json.dumps(state, default=str)  # some deployments want state as text
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{r.status_code}: {r.text[:200]}"
                time.sleep(0.5 * 2**attempt)
                continue
            if r.status_code >= 400:
                raise JevError(f"Jev request failed ({r.status_code}): {r.text[:300]}")
            j = r.json()
            if not isinstance(j.get("answers"), dict):
                raise JevError("Jev response has no answers")
            return j
        raise JevError(f"Jev unavailable: {last}")


def questions(side: str) -> dict[str, Any]:
    direction = "long (buy)" if side == "buy" else "short (sell)"
    return {
        "worth_taking": {
            "type": "noul",
            "instructions": (
                f"Taking this {direction} entry now is a good trade: over the next few bars price is more "
                "likely to move in the trade's favour enough to make a profit after fees than to hit the "
                "protective stop."),
            "criteria": {
                "true": "The setup, trend, momentum and recent results support the entry; a profit is more likely than the stop.",
                "false": "The entry is against the prevailing move, late, overextended, in a regime where this "
                         "strategy tends to lose, or otherwise more likely to be stopped out.",
            },
        },
        "regime": {
            "type": "choice",
            "instructions": "Which market regime is this symbol in right now?",
            "criteria": dict(REGIMES),
        },
    }


def market_facts(symbol: str, df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    """Computed market facts for Jev (it judges situations; it doesn't do arithmetic)."""
    ac = asset_class_of(symbol).value
    snap = market_snapshot(df, timeframe, ac)
    last = snap["last"]
    lo, hi = snap["range_100"]
    pos_in_range = (last - lo) / (hi - lo) if hi > lo else 0.5
    return {
        "symbol": symbol, "asset_class": ac, "bar_timeframe": timeframe,
        "trend_vs_sma50_sma200": snap["trend_sma50_200"],
        "change_last_24_bars_pct": _pct(snap["chg_24"]), "change_last_100_bars_pct": _pct(snap["chg_100"]),
        "rsi14": snap["rsi14"], "annualised_volatility_pct": _pct(snap["vol_annual"]),
        "atr_pct_of_price": _pct(snap["atr_pct"]),
        "position_in_100_bar_range": _label(pos_in_range, [(0.2, "near the low"), (0.4, "lower half"),
                                                           (0.6, "middle"), (0.8, "upper half")], "near the high"),
        **_level_facts(df),
    }


def _level_facts(df: pd.DataFrame) -> dict[str, Any]:
    """Key levels and volatility maths (price action + BSM), as plain facts."""
    from .context import price_context

    try:
        cx = price_context(df, None, horizon_bars=24)
    except Exception:  # noqa: BLE001 - facts are best effort
        return {}
    em = cx.get("expected_move") or {}
    return {
        "nearest_support": cx.get("nearest_support"), "nearest_support_distance_pct": cx.get("support_dist_pct"),
        "nearest_resistance": cx.get("nearest_resistance"),
        "nearest_resistance_distance_pct": cx.get("resistance_dist_pct"),
        "typical_move_next_24_bars_pct": em.get("sigma_pct"),
        "last_24_bar_move_in_sigmas": cx.get("stretch_z_24"),
    }


def build_state(sig: Signal, dec: RiskDecision, acct: Account, df: pd.DataFrame, timeframe: str,
                recent: dict[str, Any], lessons: list[str]) -> dict[str, Any]:
    """Everything numeric is computed here; Jev gets plain facts, not arithmetic to do."""
    side = dec.order.side.value if dec.order else ("buy" if sig.target > 0 else "sell")
    last = float(df["close"].iloc[-1])
    stop_dist = (2.0 * sig.atr / last) if sig.atr and last else None
    return {
        "market": market_facts(sig.symbol, df, timeframe),
        "proposed_trade": {
            "side": side, "strategy": sig.strategy, "strategy_style": STRATEGY_STYLE.get(sig.strategy, sig.strategy),
            "signal": sig.reason[:300], "stop_distance_pct": _pct(stop_dist),
            "size_pct_of_equity": _pct(abs(dec.desired_notional) / acct.equity) if acct.equity else None,
            "already_holding": "yes" if dec.current_notional else "no",
        },
        "recent_results_for_this_strategy_and_symbol": recent,
        "lessons_from_past_trading": lessons[-6:],
    }


def _pct(v: float | None) -> float | None:
    return None if v is None or not math.isfinite(v) else round(100 * v, 2)


def _label(v: float, bands: list[tuple[float, str]], top: str) -> str:
    for edge, name in bands:
        if v < edge:
            return name
    return top


@dataclass
class JevVerdict:
    p: float
    regime: str | None
    regime_conf: float | None
    mult: float
    verdict: str  # approve | reduce | veto (what gate mode would do)
    cost: float
    model: str


class JevReviewer:
    """Scores entries; in gate mode the engine applies `mult`, in shadow mode it only records."""

    def __init__(self, client: JevClient, cfg: dict[str, Any], timeframe: str = "1h", journal: Any = None,
                 book: Any = None, lessons: Any = None) -> None:
        self.client = client
        self.c = cfg
        self.timeframe = timeframe
        self.journal = journal
        self.book = book
        self.lessons = lessons
        if cfg.get("mode") not in ("shadow", "gate"):
            raise ValueError("jev.mode must be shadow or gate")
        if not 0 <= cfg["veto_below"] <= cfg["reduce_below"] <= 1:
            raise ValueError("jev: need 0 <= veto_below <= reduce_below <= 1")

    def recent(self, strategy: str, symbol: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.journal is not None:
            rows = self.journal.rows(
                "SELECT realized_pnl FROM fills WHERE symbol=? AND strategy=? AND realized_pnl IS NOT NULL "
                "ORDER BY id DESC LIMIT 20", (symbol, strategy))
            pnl = [r["realized_pnl"] for r in rows]
            out["live_closed_trades"] = len(pnl)
            if pnl:
                out["live_win_rate_pct"] = round(100 * sum(1 for x in pnl if x > 0) / len(pnl), 1)
                out["live_net_result"] = "profit" if sum(pnl) > 0 else "loss"
                out["last_trade_result"] = "win" if pnl[0] > 0 else "loss"
        if self.book is not None:
            h = (self.book.entry(symbol).get("metrics") or {}).get("holdout")
            if h:
                out["backtest_holdout_sharpe"] = round(float(h.get("sharpe", 0)), 2)
                out["backtest_holdout_win_rate_pct"] = round(100 * float(h.get("win_rate", 0)), 1)
        return out

    def review(self, sig: Signal, dec: RiskDecision, acct: Account, df: pd.DataFrame) -> JevVerdict:
        lessons = self.lessons.entries() if self.lessons is not None else []
        state = build_state(sig, dec, acct, df, self.timeframe, self.recent(sig.strategy, sig.symbol), lessons)
        side = dec.order.side.value if dec.order else ("buy" if sig.target > 0 else "sell")
        return self.score(state, side)

    @property
    def gating(self) -> bool:
        return self.c.get("mode") == "gate"

    def verdict_for(self, p: float) -> tuple[str, float]:
        if p < self.c["veto_below"]:
            return "veto", 0.0
        if p < self.c["reduce_below"]:
            return "reduce", 0.5
        return "approve", 1.0

    def score(self, state: dict[str, Any], side: str) -> JevVerdict:
        resp = self.client.decide(state, questions(side))
        a = resp["answers"]
        w = a.get("worth_taking") or {}
        p = w.get("noul")
        if not isinstance(p, (int, float)) or not 0 <= float(p) <= 1:
            raise JevError(f"Jev returned no usable probability: {w}")
        r = a.get("regime") or {}
        verdict, mult = self.verdict_for(float(p))
        return JevVerdict(p=float(p), regime=r.get("choice"), regime_conf=r.get("confidence"), mult=mult,
                          verdict=verdict, cost=float((resp.get("usage") or {}).get("cost") or 0.0),
                          model=str(resp.get("model") or self.client.model))


def report(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Calibration of Jev's worth_taking probability against realised trade outcomes."""
    resolved = [r for r in rows if r.get("closed_ts") and r.get("taken")]
    buckets = [("p < %.2f (would veto)" % cfg["veto_below"], 0.0, cfg["veto_below"]),
               ("%.2f–%.2f (would halve)" % (cfg["veto_below"], cfg["reduce_below"]), cfg["veto_below"],
                cfg["reduce_below"]),
               ("%.2f–0.70" % cfg["reduce_below"], cfg["reduce_below"], 0.70),
               ("p ≥ 0.70", 0.70, 1.01)]
    out_b = []
    for name, lo, hi in buckets:
        rs = [r for r in resolved if lo <= r["p"] < hi]
        wins = sum(1 for r in rs if (r["outcome_pnl"] or 0) > 0)
        out_b.append({"bucket": name, "trades": len(rs), "win_rate": round(wins / len(rs), 3) if rs else None,
                      "avg_p": round(sum(r["p"] for r in rs) / len(rs), 3) if rs else None,
                      "pnl": round(sum(r["outcome_pnl"] or 0 for r in rs), 2)})
    brier = (sum((r["p"] - (1.0 if (r["outcome_pnl"] or 0) > 0 else 0.0)) ** 2 for r in resolved) / len(resolved)
             if resolved else None)
    base = sum(1 for r in resolved if (r["outcome_pnl"] or 0) > 0) / len(resolved) if resolved else None
    brier_ref = base * (1 - base) if base is not None else None  # always predicting the base rate
    would_veto = [r for r in resolved if r["p"] < cfg["veto_below"]]
    would_halve = [r for r in resolved if cfg["veto_below"] <= r["p"] < cfg["reduce_below"]]
    saved = -sum(r["outcome_pnl"] or 0 for r in would_veto) - 0.5 * sum(r["outcome_pnl"] or 0 for r in would_halve)
    n_needed = int(cfg.get("min_shadow_trades", 30))
    if len(resolved) < n_needed:
        rec = f"Keep shadowing: {len(resolved)}/{n_needed} scored trades have closed."
    elif brier is not None and brier_ref is not None and brier < brier_ref and saved > 0:
        rec = (f"Jev beat the base rate (Brier {brier:.3f} vs {brier_ref:.3f}) and gating would have added "
               f"{saved:+.2f}. Consider jev.mode: gate.")
    else:
        rec = "Jev has not shown an edge on your trades yet: keep it in shadow mode (or leave it off)."
    regimes: dict[str, dict[str, Any]] = {}
    for r in resolved:
        g = regimes.setdefault(r.get("regime") or "unknown", {"trades": 0, "wins": 0, "pnl": 0.0})
        g["trades"] += 1
        g["wins"] += 1 if (r["outcome_pnl"] or 0) > 0 else 0
        g["pnl"] = round(g["pnl"] + (r["outcome_pnl"] or 0), 2)
    return {
        "mode": cfg.get("mode", "shadow"), "veto_below": cfg["veto_below"], "reduce_below": cfg["reduce_below"],
        "scored": len(rows), "taken": sum(1 for r in rows if r.get("taken")), "resolved": len(resolved),
        "open": sum(1 for r in rows if r.get("taken") and not r.get("closed_ts")),
        "errors": sum(1 for r in rows if r.get("error")),
        "cost_usd": round(sum(r.get("cost") or 0 for r in rows), 6),
        "brier": None if brier is None else round(brier, 4),
        "brier_base_rate": None if brier_ref is None else round(brier_ref, 4),
        "buckets": out_b, "what_if_gate_pnl": round(saved, 2), "by_regime": regimes,
        "recommendation": rec,
    }
