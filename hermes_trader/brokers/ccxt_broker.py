"""Crypto exchanges via ccxt (Binance, Bybit, Kraken, OKX, Coinbase, ... 100+ venues). Spot only.

Keys come from env: CCXT_API_KEY / CCXT_SECRET / CCXT_PASSWORD (passphrase venues),
or exchange-specific BINANCE_API_KEY / BINANCE_SECRET etc. which take priority.
`sandbox: true` routes to the exchange testnet when ccxt supports one.
"""

from __future__ import annotations

import json
import os
import time
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
        self.poll_attempts, self.poll_interval, self._sleep = 10, 0.5, time.sleep
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
    @staticmethod
    def quote_of(symbols: list[str]) -> str:
        quotes = {s.split("/")[1] for s in symbols} or {"USDT"}
        if len(quotes) > 1:
            raise ValueError(f"ccxt broker needs one quote currency for all symbols, got {sorted(quotes)} "
                             "(e.g. use BTC/USDT + ETH/USDT, not ETH/BTC)")
        return quotes.pop()

    def account(self, symbols: list[str] | None = None) -> Account:
        """Bot capital = free+locked quote balance + positions the bot itself opened.

        Positions come from the bot's own ledger (capped by the real balance), so coins
        you held before the bot started are never counted, sized against, or sold.
        """
        symbols = symbols or []
        quote = self.quote_of(symbols)
        bal = self.x.fetch_balance()
        totals: dict[str, float] = {k: float(v) for k, v in (bal.get("total") or {}).items() if v}
        cash = float((bal.get("free") or {}).get(quote, 0.0) or 0.0)
        equity = float(totals.get(quote, 0.0))
        positions: dict[str, Position] = {}
        for sym in symbols:
            led = self.basis.get(sym)
            if not led or led.get("qty", 0) <= 0:
                continue
            qty = min(led["qty"], totals.get(sym.split("/")[0], 0.0))
            m = self.markets.get(sym, {})
            min_amt = ((m.get("limits") or {}).get("amount") or {}).get("min") or 0.0
            if qty <= 0 or qty < min_amt:
                continue  # dust the exchange won't let us trade
            px = self.last_price(sym)
            positions[sym] = Position(sym, qty, led["avg_price"], px)
            equity += qty * px
        return Account(cash=cash, equity=equity, positions=positions, currency=quote)

    # ---- orders -------------------------------------------------------
    def _settle(self, o: dict[str, Any], symbol: str, amount: float, market: bool) -> dict[str, Any]:
        """Some venues ack market orders before they fill: poll, then cancel any unfilled remainder."""
        for _ in range(self.poll_attempts):
            if o.get("status") in ("closed", "canceled", "rejected", "expired") or float(o.get("filled") or 0) >= amount:
                return o
            self._sleep(self.poll_interval)
            try:
                o = self.x.fetch_order(o["id"], symbol)
            except Exception:  # noqa: BLE001 - venue may not support fetch_order
                break
        if market and o.get("status") == "open":
            try:
                self.x.cancel_order(o["id"], symbol)
                o = {**o, "status": "canceled"}
            except Exception:  # noqa: BLE001
                pass
        return o

    def submit(self, order: Order) -> Fill:
        m = self.markets[order.symbol]
        base, quote = order.symbol.split("/")
        amount = float(self.x.amount_to_precision(order.symbol, order.qty))
        price = self.last_price(order.symbol)
        limits = m.get("limits") or {}
        min_amt = (limits.get("amount") or {}).get("min") or 0.0
        min_cost = (limits.get("cost") or {}).get("min") or 0.0
        if amount <= 0 or amount < min_amt or amount * price < min_cost:
            return Fill("", order.symbol, order.side, 0.0, price, status="rejected",
                        raw={"error": f"below exchange minimum (amount {amount}, min {min_amt}, min cost {min_cost})"})
        params = {"clientOrderId": order.client_id} if order.client_id else {}
        market = order.type != "limit"
        o = self.x.create_order(order.symbol, "market" if market else "limit", order.side.value, amount,
                                None if market else order.limit_price, params)
        o = self._settle(o, order.symbol, amount, market)
        filled = float(o.get("filled") or 0.0)
        if not filled and market and o.get("status") not in ("canceled", "rejected", "expired"):
            # venue never confirmed (no fetch_order / cancel support). Market orders virtually always
            # fill, so track it; account() caps ledger qty by the real balance if it didn't.
            filled, o = amount, {**o, "assumed_fill": True}
        cost = float(o.get("cost") or 0.0)
        avg = float(o.get("average") or (cost / filled if filled and cost else 0.0) or o.get("price") or price)
        fee_quote, base_fee = 0.0, 0.0
        for f in o.get("fees") or ([o["fee"]] if o.get("fee") else []):
            c, cur = float(f.get("cost") or 0.0), f.get("currency")
            if cur == base:
                base_fee += c
                fee_quote += c * avg
            elif cur == quote or cur is None:
                fee_quote += c
        if filled:
            net = filled - base_fee if order.side == Side.BUY else filled
            self._update_basis(order.symbol, order.side, net, avg)
        status = "filled" if filled else ("accepted" if o.get("status") == "open" else "rejected")
        return Fill(str(o.get("id")), order.symbol, order.side, filled, avg, fee_quote, status=status, raw=o)

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

    def cancel_open(self, symbol: str, prefix: str = "ht-") -> int:
        n = 0
        for o in self.x.fetch_open_orders(symbol):
            cid = o.get("clientOrderId") or ""
            if cid.startswith(prefix):
                self.x.cancel_order(o["id"], symbol)
                n += 1
        return n
