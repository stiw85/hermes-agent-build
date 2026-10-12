"""Paper broker: simulated fills (fee + slippage) on any data source. State survives restarts."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from ..models import Account, Fill, Order, Position, Side
from .base import Broker


class DataSource(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: ...
    def last_price(self, symbol: str) -> float: ...


class PaperBroker(Broker):
    name = "paper"

    def __init__(
        self,
        data: DataSource,
        state_path: str | Path | None = None,
        starting_cash: float = 10_000.0,
        fee_bps: float = 10.0,
        slippage_bps: float = 5.0,
        allow_short: bool = False,
        tradable: Any = None,
    ) -> None:
        self.data = data
        self.path = Path(state_path) if state_path else None
        self.fee = fee_bps / 1e4
        self.slip = slippage_bps / 1e4
        self.allow_short = allow_short
        self._tradable = tradable
        self.state: dict[str, Any] = {"cash": starting_cash, "positions": {}, "fills": 0}
        if self.path and self.path.is_file():
            self.state = json.loads(self.path.read_text())

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2))
            tmp.replace(self.path)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return self.data.fetch_ohlcv(symbol, timeframe, limit)

    def last_price(self, symbol: str) -> float:
        return float(self.data.last_price(symbol))

    def is_tradable(self, symbol: str) -> bool:
        return self._tradable.is_tradable(symbol) if self._tradable else True

    def account(self, symbols: list[str] | None = None) -> Account:
        positions: dict[str, Position] = {}
        equity = float(self.state["cash"])
        for sym, p in self.state["positions"].items():
            px = self.last_price(sym)
            positions[sym] = Position(sym, p["qty"], p["avg_price"], px)
            equity += p["qty"] * px
        return Account(cash=float(self.state["cash"]), equity=equity, positions=positions)

    def submit(self, order: Order, price: float | None = None) -> Fill:
        px = price if price is not None else self.last_price(order.symbol)
        fill_px = px * (1 + self.slip) if order.side == Side.BUY else px * (1 - self.slip)
        signed = order.qty if order.side == Side.BUY else -order.qty
        pos = self.state["positions"].get(order.symbol, {"qty": 0.0, "avg_price": 0.0})
        new_qty = pos["qty"] + signed
        oid = order.client_id or uuid.uuid4().hex[:12]
        if new_qty < -1e-12 and not self.allow_short:
            return Fill(oid, order.symbol, order.side, 0.0, fill_px, 0.0, status="rejected",
                        raw={"error": "short selling disabled"})
        notional = order.qty * fill_px
        fee = notional * self.fee
        if order.side == Side.BUY and notional + fee > self.state["cash"] + 1e-9 and pos["qty"] >= 0:
            return Fill(oid, order.symbol, order.side, 0.0, fill_px, 0.0, status="rejected",
                        raw={"error": "insufficient cash"})
        self.state["cash"] -= signed * fill_px + fee
        if abs(new_qty) < 1e-12:
            self.state["positions"].pop(order.symbol, None)
        else:
            if pos["qty"] == 0 or (pos["qty"] > 0) != (new_qty > 0):
                avg = fill_px  # opened or flipped
            elif abs(new_qty) > abs(pos["qty"]):
                avg = (pos["qty"] * pos["avg_price"] + signed * fill_px) / new_qty
            else:
                avg = pos["avg_price"]  # reduced: cost basis unchanged
            self.state["positions"][order.symbol] = {"qty": new_qty, "avg_price": avg}
        self.state["fills"] += 1
        self._save()
        return Fill(oid, order.symbol, order.side, order.qty, fill_px, fee)

    def reset(self, starting_cash: float) -> None:
        self.state = {"cash": starting_cash, "positions": {}, "fills": 0}
        self._save()
