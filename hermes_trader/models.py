"""Plain data types shared by every layer (brokers, engine, backtester, agent)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    EQUITY = "equity"


@dataclass
class Order:
    symbol: str
    side: Side
    qty: float
    type: str = "market"  # market | limit
    limit_price: float | None = None
    client_id: str | None = None
    reason: str = ""

    def notional(self, price: float) -> float:
        return abs(self.qty) * price


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float = 0.0
    ts: datetime = field(default_factory=utcnow)
    status: str = "filled"  # filled | accepted | rejected
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        d["ts"] = self.ts.isoformat()
        d.pop("raw", None)
        return d


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float
    market_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * (self.market_price or self.avg_price)

    @property
    def unrealized_pnl(self) -> float:
        return (self.market_price - self.avg_price) * self.qty if self.market_price else 0.0


@dataclass
class Account:
    cash: float
    equity: float
    positions: dict[str, Position] = field(default_factory=dict)
    currency: str = "USD"


@dataclass
class Signal:
    """A strategy's opinion: desired exposure as a fraction of allowed size.

    target: -1.0 (full short) .. 0.0 (flat) .. 1.0 (full long). Long-only
    deployments clamp negatives to 0 in the risk layer.
    """

    symbol: str
    target: float
    strategy: str
    confidence: float = 1.0
    reason: str = ""
    price: float = 0.0
    atr: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
