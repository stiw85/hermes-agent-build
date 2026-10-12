"""Crypto exchanges via ccxt (Binance, Bybit, Kraken, OKX, Coinbase, ... 100+ venues). Spot only.

Keys come from env: CCXT_API_KEY / CCXT_SECRET / CCXT_PASSWORD (passphrase venues),
or exchange-specific BINANCE_API_KEY / BINANCE_SECRET etc. which take priority.
`sandbox: true` routes to the exchange testnet when ccxt supports one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from ..backtest import timeframe_seconds
from ..models import Account, Fill, Order, Position, Side
from .base import Broker, to_frame


def _env(exchange: str, key: str) -> str | None:
    return os.environ.get(f"{exchange.upper()}_{key}") or os.environ.get(f"CCXT_{key}")


class CCXTBroker(Broker):
    name = "ccxt"

    def __init__(
        self,
        exchange: str = "binance",
        sandbox: bool = True,
        state_path: str | Path | None = None,
        client: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.exchange_id = exchange
        if client is None:
            try:
                import ccxt  # noqa: PLC0415 - optional dependency
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("pip install 'hermes-trader[crypto]' (needs ccxt)") from e
            params: dict[str, Any] = {"enableRateLimit": True, "options": {"defaultType": "spot", **(options or {})}}
            for k, field in (("API_KEY", "apiKey"), ("SECRET", "secret"), ("PASSWORD", "password")):
                v = _env(exchange, k)
                if v:
                    params[field] = v
            client = getattr(ccxt, exchange)(params)
            if sandbox:
                client.set_sandbox_mode(True)
        self.x = client
        self._markets: dict[str, Any] | None = None
        # spot venues don't report cost basis, so we keep our own ledger
        self.path = Path(state_path) if state_path else None
        self.basis: dict[str, dict[str, float]] = {}
        if self.path and self.path.is_file():
            self.basis = json.loads(self.path.read_text())

    @property
    def markets(self) -> dict[str, Any]:
        if self._markets is None:
            self._markets = self.x.load_markets()
        return self._markets

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.basis, indent=2))

    # ---- data ---------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        page = 1000
        if limit <= page:
            return to_frame(self.x.fetch_ohlcv(symbol, timeframe, limit=limit)).tail(limit)
        step_ms = timeframe_seconds(timeframe) * 1000
        since = self.x.milliseconds() - (limit + 1) * step_ms
        rows: list[list[float]] = []
        while len(rows) < limit + 1:
            batch = self.x.fetch_ohlcv(symbol, timeframe, since=since, limit=page)
            if not batch:
                break
            rows.extend(batch)
            if batch[-1][0] + step_ms > self.x.milliseconds() or len(batch) < 2:
                break
            since = batch[-1][0] + step_ms
        return to_frame(rows).tail(limit)

    def last_price(self, symbol: str) -> float:
        t = self.x.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or t["bid"])

    # ---- account ------------------------------------------------------
    def account(self, symbols: list[str] | None = None) -> Account:
        bal = self.x.fetch_balance()
        totals: dict[str, float] = {k: float(v) for k, v in (bal.get("total") or {}).items() if v}
        quotes = {s.split("/")[1] for s in (symbols or [])} or {"USDT"}
        quote = sorted(quotes)[0]
        cash = float((bal.get("free") or {}).get(quote, 0.0) or 0.0)
        equity = float(totals.get(quote, 0.0))
        positions: dict[str, Position] = {}
        for sym in symbols or []:
            base = sym.split("/")[0]
            qty = totals.get(base, 0.0)
            if not qty:
                continue
            px = self.last_price(sym)
            m = self.markets.get(sym, {})
            min_amt = ((m.get("limits") or {}).get("amount") or {}).get("min") or 0.0
            if qty <= (min_amt or 0.0):
                continue  # dust
            avg = self.basis.get(sym, {}).get("avg_price", px)
            positions[sym] = Position(sym, qty, avg, px)
            equity += qty * px
        return Account(cash=cash, equity=equity, positions=positions, currency=quote)

    # ---- orders -------------------------------------------------------
    def submit(self, order: Order) -> Fill:
        m = self.markets[order.symbol]
        amount = float(self.x.amount_to_precision(order.symbol, order.qty))
        price = self.last_price(order.symbol)
        limits = m.get("limits") or {}
        min_amt = (limits.get("amount") or {}).get("min") or 0.0
        min_cost = (limits.get("cost") or {}).get("min") or 0.0
        if amount <= 0 or amount < min_amt or amount * price < min_cost:
            return Fill("", order.symbol, order.side, 0.0, price, status="rejected",
                        raw={"error": f"below exchange minimum (amount {amount}, min {min_amt}, min cost {min_cost})"})
        params = {"clientOrderId": order.client_id} if order.client_id else {}
        if order.type == "limit":
            o = self.x.create_order(order.symbol, "limit", order.side.value, amount, order.limit_price, params)
        else:
            o = self.x.create_order(order.symbol, "market", order.side.value, amount, None, params)
        filled = float(o.get("filled") or 0.0)
        avg = float(o.get("average") or o.get("price") or price)
        fee = float((o.get("fee") or {}).get("cost") or 0.0)
        if filled:
            self._update_basis(order.symbol, order.side, filled, avg)
        status = "filled" if filled else "accepted"
        return Fill(str(o.get("id")), order.symbol, order.side, filled, avg, fee, status=status, raw=o)

    def _update_basis(self, symbol: str, side: Side, qty: float, px: float) -> None:
        b = self.basis.get(symbol, {"qty": 0.0, "avg_price": 0.0})
        if side == Side.BUY:
            new_qty = b["qty"] + qty
            b["avg_price"] = (b["qty"] * b["avg_price"] + qty * px) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            b["qty"] = max(0.0, b["qty"] - qty)
            if b["qty"] == 0:
                b["avg_price"] = 0.0
        self.basis[symbol] = b
        self._save()

    def cancel_all(self, symbol: str | None = None) -> None:
        try:
            self.x.cancel_all_orders(symbol)
        except Exception:  # noqa: BLE001 - not every venue supports it
            for o in self.x.fetch_open_orders(symbol):
                self.x.cancel_order(o["id"], o["symbol"])
