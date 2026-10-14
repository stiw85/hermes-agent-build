"""Hard risk limits. Config-only: neither strategies nor the LLM can loosen these.

The risk manager turns a Signal (desired exposure) into at most one Order, or
refuses. It also owns the two circuit breakers: daily-loss halt and
max-drawdown kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Account, Order, Side, Signal


@dataclass
class RiskState:
    day: str = ""
    start_of_day_equity: float = 0.0
    peak_equity: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RiskDecision:
    order: Order | None
    approved: bool
    notes: list[str] = field(default_factory=list)
    desired_notional: float = 0.0
    current_notional: float = 0.0


class RiskManager:
    def __init__(self, cfg: dict[str, Any], allow_short: bool = False) -> None:
        self.c = cfg
        self.allow_short = allow_short

    # ---- circuit breakers ---------------------------------------------
    def roll_day(self, state: RiskState, today: str, equity: float) -> None:
        if state.day != today:
            state.day = today
            state.start_of_day_equity = equity
            state.trades_today = 0
        state.peak_equity = max(state.peak_equity or equity, equity)

    def breaker(self, state: RiskState, equity: float) -> tuple[str, str]:
        """Returns (level, reason). level: ok | reduce_only | kill."""
        if state.halted:
            return "kill", state.halt_reason or "halted"
        if state.peak_equity and equity <= state.peak_equity * (1 - self.c["max_drawdown_pct"]):
            dd = 1 - equity / state.peak_equity
            return "kill", f"drawdown {dd:.1%} >= max {self.c['max_drawdown_pct']:.0%}"
        if state.start_of_day_equity and equity <= state.start_of_day_equity * (1 - self.c["max_daily_loss_pct"]):
            loss = 1 - equity / state.start_of_day_equity
            return "reduce_only", f"daily loss {loss:.1%} >= max {self.c['max_daily_loss_pct']:.0%}"
        if state.trades_today >= self.c["max_trades_per_day"]:
            return "reduce_only", f"trade limit {self.c['max_trades_per_day']}/day reached"
        return "ok", ""

    def stop_hit(self, qty: float, avg_price: float, price: float, atr_value: float | None) -> bool:
        if not qty or not atr_value or not avg_price:
            return False
        dist = self.c["atr_stop_mult"] * atr_value
        return price <= avg_price - dist if qty > 0 else price >= avg_price + dist

    # ---- sizing --------------------------------------------------------
    def size(self, signal: Signal, account: Account, price: float, level: str = "ok",
             correlated: dict[str, float] | None = None) -> RiskDecision:
        """`correlated`: other symbols that move with this one -> their stop distance as a fraction of price."""
        c = self.c
        eq = account.equity
        notes: list[str] = []
        pos = account.positions.get(signal.symbol)
        cur_qty = pos.qty if pos else 0.0
        cur_val = cur_qty * price

        target = max(-1.0, min(1.0, signal.target * max(0.0, min(1.0, signal.confidence))))
        if not self.allow_short and target < 0:
            target = 0.0
            notes.append("short disabled -> flat")
        if level == "kill":
            target = 0.0
            notes.append("kill switch -> flatten")

        cap = c["max_position_pct"] * eq
        desired = target * cap
        if signal.atr and target != 0 and c.get("risk_per_trade_pct"):
            atr_cap = c["risk_per_trade_pct"] * eq / (c["atr_stop_mult"] * signal.atr) * price
            if atr_cap < abs(desired):
                notes.append(f"ATR sizing caps notional {abs(desired):.0f} -> {atr_cap:.0f}")
                desired = atr_cap if desired > 0 else -atr_cap

        others = sum(abs(p.qty * (p.market_price or p.avg_price)) for s, p in account.positions.items() if s != signal.symbol)
        room = max(0.0, c["max_gross_exposure_pct"] * eq - others)
        if abs(desired) > room:
            notes.append(f"gross exposure cap: {abs(desired):.0f} -> {room:.0f}")
            desired = room if desired > 0 else -room

        adding = abs(desired) > abs(cur_val) or desired * cur_val < 0

        # max open positions: no new symbol once the book is full (a position already held may change)
        max_open = int(c.get("max_open_positions") or 0)
        if max_open and adding and not cur_qty and desired:
            dust = float(c.get("min_order_notional") or 0.0)
            open_n = sum(1 for s, p in account.positions.items()
                         if s != signal.symbol and abs(p.qty * (p.market_price or p.avg_price)) >= max(dust, 1e-9))
            if open_n >= max_open:
                notes.append(f"max open positions ({max_open}) reached: no new symbol")
                desired = 0.0

        # correlated risk: positions that move together count as one bet
        corr_cap = float(c.get("correlated_risk_pct") or 0.0)
        if corr_cap and correlated and adding and desired and signal.atr and price > 0:
            # same-direction exposure in instruments that move together is one bet; opposite sides hedge
            used = sum(abs(account.positions[s].qty * (account.positions[s].market_price or account.positions[s].avg_price))
                       * stop for s, stop in correlated.items()
                       if s in account.positions and account.positions[s].qty * desired > 0)
            my_stop = c["atr_stop_mult"] * signal.atr / price
            allowed = max(0.0, corr_cap * eq - used) / my_stop if my_stop > 0 else abs(desired)
            keep = abs(cur_val) if desired * cur_val > 0 else 0.0  # never force a cut of what we already hold
            limit = max(allowed, keep)
            if abs(desired) > limit:
                notes.append(f"correlated risk cap ({', '.join(sorted(correlated))}): {abs(desired):.0f} -> {limit:.0f}")
                desired = limit if desired > 0 else -limit

        delta = desired - cur_val
        reducing = abs(desired) < abs(cur_val) and (desired * cur_val >= 0)
        closing = desired == 0 and cur_qty != 0

        if level == "reduce_only" and not (reducing or closing):
            return RiskDecision(None, False, notes + ["reduce-only: new risk blocked"], desired, cur_val)
        if not closing and abs(delta) < c["rebalance_threshold"] * cap:
            return RiskDecision(None, False, notes + [f"delta {delta:+.0f} below rebalance threshold"], desired, cur_val)
        if abs(delta) > c["max_order_notional"]:
            notes.append(f"order capped at {c['max_order_notional']:.0f}")
            delta = c["max_order_notional"] * (1 if delta > 0 else -1)
        if abs(delta) < c["min_order_notional"] and not closing:
            return RiskDecision(None, False, notes + ["below min order notional"], desired, cur_val)
        if delta > 0 and not closing and delta > account.cash * 0.999 and cur_val >= 0:
            delta = account.cash * 0.99
            notes.append("limited by available cash")
            if delta < c["min_order_notional"]:
                return RiskDecision(None, False, notes + ["insufficient cash"], desired, cur_val)

        qty = abs(cur_qty) if closing else abs(delta) / price
        side = Side.BUY if (delta > 0 if not closing else cur_qty < 0) else Side.SELL
        order = Order(signal.symbol, side, qty, reason=signal.reason)
        return RiskDecision(order, True, notes, desired, cur_val)
