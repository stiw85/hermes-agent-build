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
from typing import Any, Callable, Protocol

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


class EntryScorer(Protocol):
    """Duck type for a calibrated entry scorer such as jev.JevReviewer."""

    gating: bool
    c: dict[str, Any]

    def review(self, sig: Signal, dec: RiskDecision, acct: Account, df: pd.DataFrame) -> Any: ...
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
                 notify: Notifier | None = None, jev: EntryScorer | None = None, jev_checks: Any = None,
                 filters: Any = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.journal = journal or Journal(cfg.home / "journal.sqlite")
        self.book = book or StrategyBook(cfg.home / "strategy_book.yaml", cfg["default_strategy"])
        self.risk = RiskManager(cfg["risk"], allow_short=cfg["allow_short"])
        self.reviewer = reviewer
        self.jev = jev
        self.jev_checks = jev_checks  # jev_checks.JevChecker: regime / fit / exit every bar
        self.filters = filters  # filters.EntryFilters: deterministic entry checks (shadow / act)
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

        raw_target = sig.target  # the strategy's own view, before any stop or JEV exit overrides it
        if self.filters:
            horizon = int(self.filters.c.get("horizon_bars", 12))
            cutoff = now - pd.Timedelta(seconds=timeframe_seconds(tf) * horizon)
            self.journal.filter_resolve(sym, cutoff.isoformat(), price, now.isoformat())

        # JEV per-bar checks (one request): score old answers, ask new ones, act only to reduce risk
        regime_block, check_note = False, ""
        if self.jev_checks:
            regime_block, check_note = self._jev_checks(sym, sig, pos, df, price, now)

        # protective ATR stop + no re-entry on the same side until the strategy itself resets
        if pos and self.risk.stop_hit(pos.qty, pos.avg_price, price, sig.atr):
            self.cooldown[sym] = 1 if pos.qty > 0 else -1
            self.journal.event("stop", f"{sym}: ATR stop at {price:.6g} (avg {pos.avg_price:.6g})")
            sig.target, sig.reason = 0.0, f"ATR stop hit (avg {pos.avg_price:.4g}, px {price:.4g}); " + sig.reason
        blocked = self.cooldown.get(sym)
        if blocked:
            if raw_target * blocked > 0:
                sig.target, sig.reason = 0.0, "re-entry blocked until signal resets after a stop/exit; " + sig.reason
            else:
                self.cooldown.pop(sym, None)

        dec = self.risk.size(sig, acct, price, level)
        verdict, note = "", ""
        blocked_by = ""
        jev_id, jev_p, jev_note = None, None, ""
        if dec.order and regime_block and self._adds_risk(dec):
            dec.order, blocked_by = None, "JEV regime"
            dec.notes.append("JEV: strategy stands aside in this regime (no new risk)")
        if dec.order and self.filters and self._adds_risk(dec):
            mult = self._filters(sym, sig, dec, df, price, now)
            if mult <= 0:
                dec.order, blocked_by = None, "filters"
            elif mult < 1.0:
                dec.order.qty *= mult
                if dec.order.qty * price < self.cfg["risk"]["min_order_notional"]:
                    dec.order, blocked_by = None, "filters"
        if dec.order and self.jev and self._adds_risk(dec):
            jev_id, jev_p, jev_note = self._jev_review(sig, dec, acct, df, price)
            if dec.order is None:
                blocked_by = "JEV"
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
                blocked_by = "LLM"
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
            if jev_id and fill.status in ("filled", "accepted"):
                self.journal.jev_mark_taken(jev_id, fill.order_id)
            if realized is not None:
                self._jev_outcome(sym, realized, abs(pos.qty) - fill.qty)  # type: ignore[union-attr]
            if fill.status in ("filled", "accepted"):
                self.state.trades_today += 1
            if fill.status == "filled":
                pnl = f", realized {realized:+.2f}" if realized is not None else ""
                self.notify(f"{'🟢' if fill.side == Side.BUY else '🔴'} {sym} {action}{pnl}\n{sig.reason[:200]}")
            elif fill.status == "rejected":
                self.journal.event("reject", f"{sym}: {fill.raw.get('error', fill.raw)}")
        elif dec.approved:  # risk approved an order but review removed it
            if blocked_by.startswith("JEV") or blocked_by == "filters":
                action = f"vetoed by {blocked_by}"
            else:
                action = "vetoed" if verdict == "veto" else f"skipped after review ({verdict})"
        self.journal.decision(symbol=sym, strategy=sig.strategy, params=sig.meta.get("params"), target=sig.target,
                              price=price, signal_reason=sig.reason[:500], risk_notes=dec.notes,
                              llm_verdict=verdict, llm_note=note, action=action, jev_p=jev_p,
                              jev_note=" | ".join(x for x in (jev_note, check_note) if x) or None)
        return {"strategy": repr(strat), "target": sig.target, "price": price, "action": action,
                "notes": dec.notes, "llm": verdict or None}

    def _jev_review(self, sig: Signal, dec: RiskDecision, acct: Account, df: pd.DataFrame,
                    price: float) -> tuple[int | None, float | None, str]:
        """Score an entry with JEV. Shadow: record only. Gate: may shrink or veto (never enlarge)."""
        jc = self.jev.c  # type: ignore[union-attr]
        gating = self.jev.gating  # type: ignore[union-attr]
        side = dec.order.side.value  # type: ignore[union-attr]
        base = {"symbol": sig.symbol, "side": side, "strategy": sig.strategy, "mode": jc.get("mode", "shadow")}
        try:
            v = self.jev.review(sig, dec, acct, df)  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001 - JEV is an optional filter
            sid = self.journal.jev_score(**base, error=str(e)[:300], applied=0, taken=0)
            on_err = jc.get("on_error", "proceed")
            if gating and on_err == "veto":
                dec.order = None
            elif gating and on_err == "reduce":
                dec.order.qty *= 0.5  # type: ignore[union-attr]
            return sid, None, f"JEV error ({on_err if gating else 'shadow'}): {e}"[:300]
        applied = gating and v.mult < 1.0
        sid = self.journal.jev_score(**base, p=v.p, regime=v.regime, regime_conf=v.regime_conf, verdict=v.verdict,
                                     applied=int(applied), cost=v.cost, model=v.model, taken=0)
        note = f"JEV p={v.p:.2f}{' · ' + v.regime if v.regime else ''} → {v.verdict}{'' if gating else ' (shadow)'}"
        if applied:
            if v.mult <= 0:
                dec.order = None
            else:
                dec.order.qty *= v.mult  # type: ignore[union-attr]
                if dec.order.qty * price < self.cfg["risk"]["min_order_notional"]:  # type: ignore[union-attr]
                    dec.order = None
        return sid, v.p, note

    def _jev_checks(self, sym: str, sig: Signal, pos: Any, df: pd.DataFrame, price: float,
                    now: datetime) -> tuple[bool, str]:
        """Returns (block_new_risk, note). In act mode may also turn the signal flat to exit a position."""
        ck = self.jev_checks
        c = ck.c
        step = timeframe_seconds(self.cfg["timeframe"])
        cutoff = (now - pd.Timedelta(seconds=step * int(c["horizon_bars"]))).isoformat()
        self.journal.jev_check_resolve(sym, cutoff, price, now.isoformat())
        holding = bool(pos and pos.qty)
        base = {"ts": now.isoformat(), "symbol": sym, "strategy": sig.strategy, "price": price, "mode": c["mode"]}
        try:
            r = ck.check(sig, pos if holding else None, df)
        except Exception as e:  # noqa: BLE001 - checks are advisory
            self.journal.jev_check(**base, kind="regime", error=str(e)[:300])
            return False, f"JEV check error: {e}"[:200]
        want = 1 if sig.target > 0 else -1 if sig.target < 0 else 0
        block = ck.acting and r.fit_p is not None and r.fit_p < c["regime_block_below"] and want != 0
        self.journal.jev_check(**base, kind="regime", regime=r.regime, regime_conf=r.regime_conf, p=r.fit_p,
                               side_sign=want, applied=int(block), cost=r.cost, model=r.model)
        note = f"regime {r.regime or '?'} · fit {r.fit_p:.0%}"
        if holding and r.exit_p is not None:
            side = 1 if pos.qty > 0 else -1
            close = ck.acting and r.exit_p >= c["exit_above"]
            self.journal.jev_check(**base, kind="exit", regime=r.regime, p=r.exit_p, side_sign=side,
                                   applied=int(close), cost=0.0, model=r.model)
            note += f" · exit {r.exit_p:.0%}"
            if close:
                self.cooldown[sym] = side  # same rule as a stop: no re-entry until the strategy resets
                sig.target, sig.reason = 0.0, f"JEV exit (p={r.exit_p:.2f}); " + sig.reason
                self.journal.event("jev", f"{sym}: closing on JEV exit check (p={r.exit_p:.2f})")
        if not ck.acting:
            note += " (shadow)"
        elif block:
            note += " → standing aside"
        return block, note

    def _filters(self, sym: str, sig: Signal, dec: RiskDecision, df: pd.DataFrame, price: float,
                 now: datetime) -> float:
        """Run entry filters on a new-risk order. Notes go on the decision.

        Returns the size multiplier from filters acting in act mode: 1 = untouched, 0 = skip.
        """
        f = self.filters
        side = 1 if dec.desired_notional > 0 else -1
        base = {"ts": now.isoformat(), "symbol": sym, "strategy": sig.strategy, "side_sign": side, "price": price}
        try:
            results = f.evaluate(side, price, df, sig.atr, f.daily(sym, df, now), symbol=sym, now=now,
                                 implied=f.implied_vol(sym) if f.enabled("vol") else None)
        except Exception as e:  # noqa: BLE001 - filters are advisory; never stop trading
            log.warning("filters failed for %s: %s", sym, e)
            self.journal.filter_check(**base, name="error", passed=1, mode="", error=str(e)[:300])
            dec.notes.append(f"filters error: {e}"[:200])
            return 1.0
        mult = 1.0
        for r in results:
            mode = f.mode(r.name)
            act = mode == "act" and not r.passed
            self.journal.filter_check(**base, name=r.name, passed=int(r.passed), applied=int(act), mode=mode,
                                      value=r.value, note=r.note[:300])
            verb = "skip" if r.mult <= 0 else f"size x{r.mult:g}"
            tail = "" if r.passed else (f" → {verb}" if act else f" → would {verb} (shadow)")
            dec.notes.append(f"{r.name}: {r.note}{tail}")
            if act:
                mult = min(mult, max(0.0, r.mult))
        return mult

    def _jev_outcome(self, sym: str, realized: float, remaining_qty: float) -> None:
        self.journal.jev_add_pnl(sym, realized)
        if remaining_qty <= 1e-12:
            self.journal.jev_close(sym)

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
            if realized is not None:
                self._jev_outcome(sym, realized, abs(p.qty) - f.qty)
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
