"""The trading loop: data -> strategy signal -> stops -> risk sizing -> (LLM review) -> execute -> journal.

One call to `cycle()` = one pass over every configured symbol. Run it on bar close.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .backtest import timeframe_seconds
from .book import StrategyBook
from .brokers.base import Broker
from .config import Config
from .journal import Journal
from .models import Account, Fill, Order, Side, Signal
from .risk import RiskDecision, RiskManager, RiskState

log = logging.getLogger("hermes_trader.engine")

Reviewer = Callable[[Signal, RiskDecision, Account, pd.DataFrame], dict[str, Any]]
Notifier = Callable[[str], None]


def review_multiplier(verdict: str, size_mult: Any) -> float:
    """Interpret an LLM review. The verdict decides first; a malformed reply never enlarges a trade."""
    if verdict == "approve":
        return 1.0
    if verdict == "veto":
        return 0.0
    if verdict == "reduce":
        try:
            m = float(size_mult)
        except (TypeError, ValueError):
            return 0.5
        return 0.5 if not 0.0 < m < 1.0 else m
    raise ValueError(f"unrecognised verdict {verdict!r}")


def closed_bars(df: pd.DataFrame, timeframe: str, now: datetime) -> pd.DataFrame:
    """Drop the still-forming candle that most venues return as the last row."""
    if df.empty:
        return df
    step = pd.Timedelta(seconds=timeframe_seconds(timeframe))
    return df[df.index + step <= pd.Timestamp(now)]


class Engine:
    def __init__(self, cfg: Config, broker: Broker, journal: Journal | None = None,
                 book: StrategyBook | None = None, reviewer: Reviewer | None = None,
                 notify: Notifier | None = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.journal = journal or Journal(cfg.home / "journal.sqlite")
        self.book = book or StrategyBook(cfg.home / "strategy_book.yaml", cfg["default_strategy"])
        self.risk = RiskManager(cfg["risk"], allow_short=cfg["allow_short"])
        self.reviewer = reviewer
        self.notify = notify or (lambda msg: None)
        self.state_path: Path = cfg.home / "engine_state.json"
        raw = json.loads(self.state_path.read_text()) if self.state_path.is_file() else {}
        self.state = RiskState(**{k: v for k, v in raw.get("risk", {}).items() if k in RiskState.__dataclass_fields__})
        self.cooldown: dict[str, int] = raw.get("cooldown", {})  # symbol -> side sign blocked after a stop
        self.meta: dict[str, Any] = raw.get("meta", {})

    @property
    def symbols(self) -> list[str]:
        return list(self.cfg["symbols"])

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"risk": self.state.to_dict(), "cooldown": self.cooldown, "meta": self.meta},
                                  indent=2))
        tmp.replace(self.state_path)

    # ------------------------------------------------------------------
    def cycle(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        acct = self.broker.account(self.symbols)
        self.risk.roll_day(self.state, now.date().isoformat(), acct.equity)
        level, why = self.risk.breaker(self.state, acct.equity)
        if level == "kill" and not self.state.halted:
            self.state.halted, self.state.halt_reason = True, why
            self.journal.event("halt", why, {"equity": acct.equity, "peak": self.state.peak_equity})
            self.notify(f"🛑 KILL SWITCH: {why}. Flattening and halting. Run `hermes-trader resume` to restart.")
        gross = sum(abs(p.market_value) for p in acct.positions.values())
        self.journal.equity(acct.equity, acct.cash, gross)

        report: dict[str, Any] = {"ts": now.isoformat(), "equity": round(acct.equity, 2), "level": level,
                                  "why": why, "symbols": {}}
        if level == "kill":
            # flatten everything (incl. dust and symbols whose data failed), then do nothing else
            if any(p.qty for p in acct.positions.values()):
                report["flatten"] = self.flatten(f"kill switch: {why}")
            self.meta["last_cycle"] = now.isoformat()
            self.save()
            return report
        for sym in self.symbols:
            try:
                report["symbols"][sym] = self._symbol(sym, acct, level, now)
                acct = self.broker.account(self.symbols)
            except Exception as e:  # one bad symbol must not stop the others
                log.exception("cycle failed for %s", sym)
                self.journal.event("error", f"{sym}: {e}")
                report["symbols"][sym] = {"error": str(e)}
        self.meta["last_cycle"] = now.isoformat()
        self.save()
        return report

    def _symbol(self, sym: str, acct: Account, level: str, now: datetime) -> dict[str, Any]:
        if not self.broker.is_tradable(sym):
            return {"action": "skip", "why": "market closed"}
        tf = self.cfg["timeframe"]
        df = closed_bars(self.broker.fetch_ohlcv(sym, tf, self.cfg["history_bars"]), tf, now)
        if df.empty:
            return {"action": "skip", "why": "no data"}
        strat = self.book.strategy_for(sym)
        sig = strat.signal(sym, df)
        price = self.broker.last_price(sym)
        pos = acct.positions.get(sym)

        # stale bot orders from a previous cycle would stack on top of the new one
        self.broker.cancel_open(sym)

        # protective ATR stop + no re-entry on the same side until the strategy itself resets
        raw_target = sig.target
        if pos and self.risk.stop_hit(pos.qty, pos.avg_price, price, sig.atr):
            self.cooldown[sym] = 1 if pos.qty > 0 else -1
            self.journal.event("stop", f"{sym}: ATR stop at {price:.6g} (avg {pos.avg_price:.6g})")
            sig.target, sig.reason = 0.0, f"ATR stop hit (avg {pos.avg_price:.4g}, px {price:.4g}); " + sig.reason
        blocked = self.cooldown.get(sym)
        if blocked:
            if raw_target * blocked > 0:
                sig.target, sig.reason = 0.0, "re-entry blocked until signal resets after stop; " + sig.reason
            else:
                self.cooldown.pop(sym, None)

        dec = self.risk.size(sig, acct, price, level)
        verdict, note = "", ""
        if dec.order and self.reviewer and self._adds_risk(dec):
            try:
                rv = self.reviewer(sig, dec, acct, df)
                verdict, note = str(rv.get("verdict", "")).strip().lower(), str(rv.get("note", ""))[:500]
                mult = review_multiplier(verdict, rv.get("size_mult"))
            except Exception as e:
                on_err = self.cfg["llm"].get("on_review_error", "reduce")
                mult = {"proceed": 1.0, "veto": 0.0}.get(on_err, 0.5)
                verdict, note = "error", f"review failed ({on_err}, x{mult}): {e}"[:300]
            if mult <= 0:
                dec.order, verdict = None, "veto" if verdict != "error" else verdict
            elif mult < 1.0:
                dec.order.qty *= mult
                if dec.order.qty * price < self.cfg["risk"]["min_order_notional"]:
                    dec.order = None

        action = "hold"
        fill: Fill | None = None
        if dec.order:
            dec.order.client_id = f"ht-{uuid.uuid4().hex[:16]}"
            fill = self.broker.submit(dec.order)
            action = f"{fill.side.value} {fill.qty:.6g} @ {fill.price:.6g} ({fill.status})"
            realized = None
            if fill.status == "filled" and fill.qty and pos and pos.qty:
                reducing = (pos.qty > 0 and fill.side == Side.SELL) or (pos.qty < 0 and fill.side == Side.BUY)
                if reducing:
                    q = min(abs(pos.qty), fill.qty)
                    sign = 1 if pos.qty > 0 else -1
                    realized = (fill.price - pos.avg_price) * q * sign - fill.fee
            self.journal.fill(order_id=fill.order_id, symbol=sym, side=fill.side.value, qty=fill.qty,
                              price=fill.price, fee=fill.fee, status=fill.status, strategy=sig.strategy,
                              reason=sig.reason[:500], realized_pnl=realized)
            if fill.status in ("filled", "accepted"):
                self.state.trades_today += 1
            if fill.status == "filled":
                pnl = f", realized {realized:+.2f}" if realized is not None else ""
                self.notify(f"{'🟢' if fill.side == Side.BUY else '🔴'} {sym} {action}{pnl}\n{sig.reason[:200]}")
            elif fill.status == "rejected":
                self.journal.event("reject", f"{sym}: {fill.raw.get('error', fill.raw)}")
        elif dec.approved:  # risk approved an order but review removed it
            action = "vetoed" if verdict == "veto" else f"skipped after review ({verdict})"
        self.journal.decision(symbol=sym, strategy=sig.strategy, params=sig.meta.get("params"), target=sig.target,
                              price=price, signal_reason=sig.reason[:500], risk_notes=dec.notes,
                              llm_verdict=verdict, llm_note=note, action=action)
        return {"strategy": repr(strat), "target": sig.target, "price": price, "action": action,
                "notes": dec.notes, "llm": verdict or None}

    @staticmethod
    def _adds_risk(dec: RiskDecision) -> bool:
        return abs(dec.desired_notional) > abs(dec.current_notional) or dec.desired_notional * dec.current_notional < 0

    # ------------------------------------------------------------------
    def flatten(self, reason: str = "manual flatten") -> list[dict[str, Any]]:
        acct = self.broker.account(self.symbols)
        out = []
        for sym in self.symbols:
            self.broker.cancel_open(sym)
        for sym, p in acct.positions.items():
            if not p.qty:
                continue
            o = Order(sym, Side.SELL if p.qty > 0 else Side.BUY, abs(p.qty), reason=reason)
            f = self.broker.submit(o)
            realized = (f.price - p.avg_price) * min(abs(p.qty), f.qty) * (1 if p.qty > 0 else -1) - f.fee \
                if f.status == "filled" else None
            self.journal.fill(order_id=f.order_id, symbol=sym, side=f.side.value, qty=f.qty, price=f.price,
                              fee=f.fee, status=f.status, strategy="flatten", reason=reason, realized_pnl=realized)
            out.append(f.to_dict())
        self.journal.event("flatten", reason, out)
        return out

    def halt(self, reason: str) -> None:
        self.state.halted, self.state.halt_reason = True, reason
        self.journal.event("halt", reason)
        self.save()

    def resume(self) -> None:
        eq = self.broker.account(self.symbols).equity
        self.state.halted, self.state.halt_reason = False, ""
        self.state.peak_equity = eq  # reset drawdown baseline deliberately
        self.state.start_of_day_equity = eq
        self.journal.event("resume", f"resumed at equity {eq:.2f}")
        self.save()

    def status(self) -> dict[str, Any]:
        acct = self.broker.account(self.symbols)
        return {
            "mode": self.cfg["mode"], "broker": self.broker.name, "equity": round(acct.equity, 2),
            "cash": round(acct.cash, 2), "currency": acct.currency,
            "positions": {s: {"qty": p.qty, "avg": p.avg_price, "px": p.market_price,
                              "upnl": round(p.unrealized_pnl, 2)} for s, p in acct.positions.items()},
            "risk": asdict(self.state), "strategies": {s: self.book.entry(s).get("strategy") for s in self.symbols},
            "last_cycle": self.meta.get("last_cycle"),
        }
