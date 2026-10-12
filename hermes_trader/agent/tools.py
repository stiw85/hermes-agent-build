"""Trading tools exposed to the LLM. Every write path goes through the same gates as the bot."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..backtest import backtest, buy_and_hold, periods_per_year
from ..brokers.base import asset_class_of
from ..engine import Engine
from ..improve import Improver
from ..models import Order, Side, utcnow
from ..strategies import describe, make
from .memory import Lessons, Playbooks

Confirm = Callable[[str], bool]


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def market_snapshot(df: pd.DataFrame, timeframe: str, asset_class: str) -> dict[str, Any]:
    c = df["close"]
    r = c.pct_change().dropna()
    ppy = periods_per_year(timeframe, asset_class)
    s50, s200 = ind.sma(c, 50).iloc[-1], ind.sma(c, 200).iloc[-1]
    a = ind.atr(df).iloc[-1]
    trend = "n/a"
    if not (math.isnan(s50) or math.isnan(s200)):
        trend = "up" if c.iloc[-1] > s50 > s200 else "down" if c.iloc[-1] < s50 < s200 else "mixed"

    def chg(n: int) -> float | None:
        return round(float(c.iloc[-1] / c.iloc[-n - 1] - 1), 4) if len(c) > n else None

    return {
        "last": float(c.iloc[-1]), "bar_time": str(df.index[-1]), "bars": len(df),
        "chg_24": chg(24), "chg_100": chg(100),
        "vol_annual": round(float(r.tail(100).std() * np.sqrt(ppy)), 4) if len(r) > 10 else None,
        "rsi14": round(float(ind.rsi(c).iloc[-1]), 1) if len(c) > 30 else None,
        "atr_pct": round(float(a / c.iloc[-1]), 4) if not math.isnan(a) else None,
        "trend_sma50_200": trend,
        "range_100": [float(c.tail(100).min()), float(c.tail(100).max())],
    }


class Toolkit:
    def __init__(self, engine: Engine, improver: Improver, lessons: Lessons, playbooks: Playbooks,
                 confirm: Confirm | None = None) -> None:
        self.e = engine
        self.cfg = engine.cfg
        self.imp = improver
        self.lessons = lessons
        self.playbooks = playbooks
        self.confirm = confirm
        self._spec: dict[str, tuple[str, dict[str, Any], Callable[..., Any]]] = {
            "get_portfolio": ("Account equity, cash, positions, risk state, active strategy per symbol.",
                              _schema({}), self.get_portfolio),
            "market_snapshot": ("Price, trend, volatility, RSI, ATR for a symbol (closed bars).",
                                _schema({"symbol": {"type": "string"}, "bars": {"type": "integer"}}, ["symbol"]),
                                self.market_snapshot),
            "list_strategies": ("Available strategies, default params and search grids.", _schema({}),
                                lambda: describe()),
            "strategy_book": ("Current strategy/params per symbol with promotion metrics.", _schema({}),
                              lambda: self.e.book.summary()),
            "run_backtest": ("Backtest a strategy on recent history (fees+slippage included).",
                             _schema({"symbol": {"type": "string"}, "strategy": {"type": "string"},
                                      "params": {"type": "object"}, "bars": {"type": "integer"}},
                                     ["symbol", "strategy"]), self.run_backtest),
            "optimize": ("Walk-forward search (train-ranked) + holdout check of the top pick. Changes nothing.",
                         _schema({"symbol": {"type": "string"},
                                  "strategies": {"type": "array", "items": {"type": "string"}}}, ["symbol"]),
                         self.optimize),
            "promote_strategy": ("Switch a symbol to strategy+params IF it passes the holdout gate. "
                                 "Max one attempt per symbol per day: pick carefully.",
                                 _schema({"symbol": {"type": "string"}, "strategy": {"type": "string"},
                                          "params": {"type": "object"}, "why": {"type": "string"}},
                                         ["symbol", "strategy", "params", "why"]), self.promote),
            "rollback_strategy": ("Revert a symbol to its previous strategy version.",
                                  _schema({"symbol": {"type": "string"}}, ["symbol"]),
                                  lambda symbol: self.e.book.rollback(symbol) or "nothing to roll back"),
            "journal_stats": ("Live realised P&L, win rate and fees by strategy/symbol; equity drawdown.",
                              _schema({}), lambda: self.e.journal.stats()),
            "recent_trades": ("Most recent fills.", _schema({"n": {"type": "integer"}}),
                              lambda n=20: self.e.journal.recent_fills(min(int(n), 100))),
            "recent_decisions": ("Most recent per-bar decisions incl. risk notes and LLM verdicts.",
                                 _schema({"n": {"type": "integer"}}),
                                 lambda n=20: self.e.journal.recent_decisions(min(int(n), 100))),
            "memory": ("Curated lessons. action=add(text) | replace(old,text) | remove(old) | view.",
                       _schema({"action": {"type": "string", "enum": ["add", "replace", "remove", "view"]},
                                "text": {"type": "string"}, "old": {"type": "string"}}, ["action"]),
                       self.memory),
            "playbook": ("Procedural playbooks. action=list | view(name) | create(name,description,body) | "
                         "patch(name,old,new).",
                         _schema({"action": {"type": "string", "enum": ["list", "view", "create", "patch"]},
                                  "name": {"type": "string"}, "description": {"type": "string"},
                                  "body": {"type": "string"}, "old": {"type": "string"},
                                  "new": {"type": "string"}}, ["action"]), self.playbook),
        }
        if confirm is not None:
            self._spec["place_order"] = (
                "Manual order (needs the human's confirmation; risk caps still apply). notional in account ccy.",
                _schema({"symbol": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
                         "notional": {"type": "number"}, "why": {"type": "string"}},
                        ["symbol", "side", "notional", "why"]), self.place_order)

    # ---- plumbing -----------------------------------------------------
    def schemas(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": n, "description": d, "parameters": p}}
                for n, (d, p, _) in self._spec.items() if only is None or n in only]

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._spec:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            out = self._spec[name][2](**(args or {}))
        except TypeError as e:
            out = {"error": f"bad arguments: {e}"}
        except Exception as e:  # tools never crash the loop
            out = {"error": f"{type(e).__name__}: {e}"}
        return json.dumps(out, default=str)[:12_000]

    def _df(self, symbol: str, bars: int) -> pd.DataFrame:
        if symbol not in self.e.symbols:
            raise ValueError(f"{symbol} not in configured symbols {self.e.symbols}")
        return self.e.broker.fetch_ohlcv(symbol, self.cfg["timeframe"], int(bars))

    # ---- tools --------------------------------------------------------
    def get_portfolio(self) -> dict[str, Any]:
        return self.e.status()

    def market_snapshot(self, symbol: str, bars: int = 300) -> dict[str, Any]:
        df = self._df(symbol, max(60, min(int(bars), 2000)))
        return market_snapshot(df, self.cfg["timeframe"], asset_class_of(symbol).value)

    def run_backtest(self, symbol: str, strategy: str, params: dict | None = None, bars: int = 1500) -> dict:
        df = self._df(symbol, min(int(bars), 10_000))
        b = self.cfg["broker"]
        r = backtest(df, make(strategy, params or {}), fee_bps=b["fee_bps"], slippage_bps=b["slippage_bps"],
                     allow_short=self.cfg["allow_short"], timeframe=self.cfg["timeframe"],
                     asset_class=asset_class_of(symbol).value)
        return {"result": r.summary(),
                "buy_and_hold": buy_and_hold(df, self.cfg["timeframe"], asset_class_of(symbol).value)}

    def optimize(self, symbol: str, strategies: list[str] | None = None) -> dict:
        df = self._df(symbol, self.cfg["improve"]["lookback_bars"])
        return self.imp.run(symbol, df, self.e.book, promote=False, strategies=strategies).to_dict()

    def promote(self, symbol: str, strategy: str, params: dict, why: str) -> dict:
        # one holdout test per symbol per cooldown: stops the agent re-rolling candidates against the same holdout
        hours = float(self.cfg["improve"].get("promote_cooldown_hours", 24))
        attempts = self.e.meta.setdefault("promote_attempts", {})
        last = attempts.get(symbol)
        now = utcnow()
        if last and (now - datetime.fromisoformat(last)).total_seconds() < hours * 3600:
            return {"promoted": False, "reason": f"one promotion attempt per {hours:g}h per symbol; last at {last}"}
        df = self._df(symbol, self.cfg["improve"]["lookback_bars"])
        make(strategy, params)
        attempts[symbol] = now.isoformat()
        self.e.save()
        cand = self.imp.evaluate(symbol, df, strategy, params)
        inc_score = self.imp.incumbent_score(symbol, df, self.e.book.entry(symbol))
        ok, reason = self.imp.gate(cand, inc_score)
        self.e.journal.event("promote_attempt", f"{symbol}: {strategy}{params} -> {ok} ({reason})", {"why": why})
        if not ok:
            return {"promoted": False, "reason": reason}
        entry = self.e.book.promote(symbol, strategy, params, {"holdout": cand.test, "score": round(cand.score, 3),
                                                               "why": why[:300]}, source="agent")
        self.e.journal.event("promote", f"{symbol}: {strategy}{params} ({reason})", {"why": why})
        return {"promoted": True, "reason": reason, "version": entry["version"]}

    def memory(self, action: str, text: str = "", old: str = "") -> str:
        if action == "view":
            return self.lessons.render()
        if action == "add":
            return self.lessons.add(text)
        if action == "replace":
            return self.lessons.replace(old, text)
        if action == "remove":
            return self.lessons.remove(old)
        return "error: unknown action"

    def playbook(self, action: str, name: str = "", description: str = "", body: str = "", old: str = "",
                 new: str = "") -> Any:
        if action == "list":
            return self.playbooks.index()
        if action == "view":
            return self.playbooks.view(name)
        if action == "create":
            return self.playbooks.create(name, description, body)
        if action == "patch":
            return self.playbooks.patch(name, old, new)
        return "error: unknown action"

    def place_order(self, symbol: str, side: str, notional: float, why: str) -> dict:
        if symbol not in self.e.symbols:
            return {"error": f"{symbol} not configured"}
        if self.e.state.halted:
            return {"error": f"trading halted: {self.e.state.halt_reason}"}
        rc = self.cfg["risk"]
        notional = float(notional)
        if notional <= 0 or notional > rc["max_order_notional"]:
            return {"error": f"notional must be in (0, {rc['max_order_notional']}]"}
        acct = self.e.broker.account(self.e.symbols)
        px = self.e.broker.last_price(symbol)
        pos = acct.positions.get(symbol)
        cur = pos.qty * px if pos else 0.0
        new = cur + (notional if side == "buy" else -notional)
        if abs(new) > rc["max_position_pct"] * acct.equity + 1e-6 and abs(new) > abs(cur):
            return {"error": f"would exceed max_position_pct ({rc['max_position_pct']:.0%} of equity)"}
        if new < -1e-9 and not self.cfg["allow_short"]:
            return {"error": "shorting disabled"}
        qty = notional / px
        if not self.confirm(f"{side.upper()} {qty:.6g} {symbol} (~{notional:.2f}) — {why}"):
            return {"error": "human declined"}
        f = self.e.broker.submit(Order(symbol, Side(side), qty, reason=f"manual: {why}"))
        self.e.journal.fill(order_id=f.order_id, symbol=symbol, side=f.side.value, qty=f.qty, price=f.price,
                            fee=f.fee, status=f.status, strategy="manual", reason=why[:300], realized_pnl=None)
        return f.to_dict()
