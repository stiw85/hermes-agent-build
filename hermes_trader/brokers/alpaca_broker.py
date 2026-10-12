"""US stocks/ETFs and crypto via Alpaca's REST API (no SDK needed).

Keys from env: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.
`paper: true` (default) uses https://paper-api.alpaca.markets — free paper account.
Symbols: equities as bare tickers (AAPL, SPY); crypto with a slash (BTC/USD).
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from ..backtest import timeframe_seconds
from ..models import Account, AssetClass, Fill, Order, Position
from .base import OHLCV_COLS, Broker, asset_class_of

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

_TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "2h": "2Hour",
       "4h": "4Hour", "1d": "1Day", "1w": "1Week"}


class AlpacaError(RuntimeError):
    pass


class AlpacaBroker(Broker):
    name = "alpaca"

    def __init__(
        self,
        paper: bool = True,
        key_id: str | None = None,
        secret: str | None = None,
        stock_feed: str = "iex",
        crypto_feed: str = "us",
        session: requests.Session | None = None,
    ) -> None:
        key_id = key_id or os.environ.get("ALPACA_API_KEY_ID")
        secret = secret or os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret:
            raise RuntimeError("set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        self.base = PAPER_URL if paper else LIVE_URL
        self.stock_feed = stock_feed
        self.crypto_feed = crypto_feed
        self.s = session or requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
        self._clock: tuple[float, bool] | None = None

    # ---- http ---------------------------------------------------------
    def _req(self, method: str, url: str, **kw: Any) -> Any:
        for attempt in range(4):
            r = self.s.request(method, url, timeout=30, **kw)
            if r.status_code == 429 and attempt < 3:
                time.sleep(2**attempt)
                continue
            if r.status_code >= 400:
                raise AlpacaError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else None
        raise AlpacaError("rate limited")

    # ---- data ---------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        tf = _TF.get(timeframe)
        if not tf:
            raise ValueError(f"Alpaca timeframe {timeframe!r} unsupported; use one of {list(_TF)}")
        crypto = asset_class_of(symbol) == AssetClass.CRYPTO
        secs = timeframe_seconds(timeframe)
        # equities trade ~6.5h/day, 5 days/week -> look back further than limit*tf
        factor = 1.3 if crypto else (1.6 if secs >= 86400 else 5.5)
        start = datetime.now(timezone.utc) - timedelta(seconds=secs * limit * factor + 86400)
        params: dict[str, Any] = {"timeframe": tf, "start": start.isoformat(), "limit": 10_000}
        if crypto:
            url = f"{DATA_URL}/v1beta3/crypto/{self.crypto_feed}/bars"
            params["symbols"] = symbol
        else:
            url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
            params.update(feed=self.stock_feed, adjustment="all")
        rows: list[dict] = []
        while True:
            j = self._req("GET", url, params=params)
            bars = (j.get("bars") or {}).get(symbol, []) if crypto else (j.get("bars") or [])
            rows.extend(bars)
            tok = j.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        if not rows:
            return pd.DataFrame(columns=OHLCV_COLS, index=pd.DatetimeIndex([], tz="UTC"))
        df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df.index = pd.DatetimeIndex(pd.to_datetime(df["t"], utc=True), name="ts")
        return df[OHLCV_COLS].astype(float).sort_index().tail(limit)

    def last_price(self, symbol: str) -> float:
        if asset_class_of(symbol) == AssetClass.CRYPTO:
            j = self._req("GET", f"{DATA_URL}/v1beta3/crypto/{self.crypto_feed}/latest/trades",
                          params={"symbols": symbol})
            return float(j["trades"][symbol]["p"])
        j = self._req("GET", f"{DATA_URL}/v2/stocks/{symbol}/trades/latest", params={"feed": self.stock_feed})
        return float(j["trade"]["p"])

    def is_tradable(self, symbol: str) -> bool:
        if asset_class_of(symbol) == AssetClass.CRYPTO:
            return True
        now = time.time()
        if not self._clock or now - self._clock[0] > 60:
            self._clock = (now, bool(self._req("GET", f"{self.base}/v2/clock")["is_open"]))
        return self._clock[1]

    # ---- account ------------------------------------------------------
    @staticmethod
    def _sym(raw: str, wanted: list[str]) -> str:
        for w in wanted:
            if w.replace("/", "") == raw:
                return w
        return raw

    def account(self, symbols: list[str] | None = None) -> Account:
        a = self._req("GET", f"{self.base}/v2/account")
        positions: dict[str, Position] = {}
        for p in self._req("GET", f"{self.base}/v2/positions") or []:
            sym = self._sym(p["symbol"], symbols or [])
            positions[sym] = Position(sym, float(p["qty"]), float(p["avg_entry_price"]), float(p["current_price"]))
        return Account(cash=float(a["cash"]), equity=float(a["equity"]), positions=positions,
                       currency=a.get("currency", "USD"))

    # ---- orders -------------------------------------------------------
    def submit(self, order: Order) -> Fill:
        crypto = asset_class_of(order.symbol) == AssetClass.CRYPTO
        body: dict[str, Any] = {
            "symbol": order.symbol,
            "qty": f"{order.qty:.9f}".rstrip("0").rstrip("."),
            "side": order.side.value,
            "type": order.type,
            "time_in_force": "gtc" if crypto else "day",
            "client_order_id": order.client_id or f"ht-{uuid.uuid4().hex[:16]}",
        }
        if order.type == "limit":
            body["limit_price"] = str(order.limit_price)
        o = self._req("POST", f"{self.base}/v2/orders", json=body)
        for _ in range(10):  # market orders usually fill within a second or two
            if o.get("status") in ("filled", "canceled", "rejected", "expired"):
                break
            time.sleep(0.5)
            o = self._req("GET", f"{self.base}/v2/orders/{o['id']}")
        if order.type == "market" and o.get("status") not in ("filled", "canceled", "rejected", "expired"):
            try:  # don't leave a working remainder that would stack on next cycle's order
                self._req("DELETE", f"{self.base}/v2/orders/{o['id']}")
                o = self._req("GET", f"{self.base}/v2/orders/{o['id']}")
            except AlpacaError:
                pass
        filled = float(o.get("filled_qty") or 0.0)
        px = float(o.get("filled_avg_price") or 0.0) or self.last_price(order.symbol)
        status = "filled" if filled else ("rejected" if o.get("status") in ("rejected", "canceled") else "accepted")
        return Fill(o["id"], order.symbol, order.side, filled, px, 0.0, status=status, raw=o)

    def cancel_open(self, symbol: str, prefix: str = "ht-") -> int:
        n = 0
        for o in self._req("GET", f"{self.base}/v2/orders", params={"status": "open", "symbols": symbol}) or []:
            if (o.get("client_order_id") or "").startswith(prefix):
                self._req("DELETE", f"{self.base}/v2/orders/{o['id']}")
                n += 1
        return n
