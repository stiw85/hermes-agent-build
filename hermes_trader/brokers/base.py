"""Broker interface. Every adapter (paper, ccxt, Alpaca) implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..models import Account, AssetClass, Fill, Order

OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def asset_class_of(symbol: str) -> AssetClass:
    """Convention: crypto pairs contain '/', equities are bare tickers."""
    return AssetClass.CRYPTO if "/" in symbol else AssetClass.EQUITY


def to_frame(rows: list[list[float]] | list[dict], ts_unit: str = "ms") -> pd.DataFrame:
    """Normalise [[ts, o, h, l, c, v], ...] into an OHLCV frame indexed by UTC timestamps."""
    if not rows:
        return pd.DataFrame(columns=OHLCV_COLS, index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame(rows, columns=["ts", *OHLCV_COLS])
    idx = pd.to_datetime(df.pop("ts"), unit=ts_unit, utc=True) if ts_unit else pd.to_datetime(df.pop("ts"), utc=True)
    df.index = pd.DatetimeIndex(idx, name="ts")
    df = df.astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


class Broker(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: ...

    @abstractmethod
    def last_price(self, symbol: str) -> float: ...

    @abstractmethod
    def account(self, symbols: list[str] | None = None) -> Account: ...

    @abstractmethod
    def submit(self, order: Order) -> Fill: ...

    def cancel_open(self, symbol: str, prefix: str = "ht-") -> int:
        """Cancel this bot's still-open orders for symbol (client ids starting with prefix). Returns count."""
        return 0

    def is_tradable(self, symbol: str) -> bool:
        """False when the venue is closed for this symbol (e.g. US equities after hours)."""
        return True

    def close(self) -> None:  # noqa: B027 - optional
        return None
