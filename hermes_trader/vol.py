"""Implied volatility feeds (the options market's own forecast of movement), cached, best effort.

- Crypto BTC/ETH: Deribit DVOL index (public, no key): 30-day implied vol, annualised %.
- US equities:    CBOE VIX daily history CSV (public): S&P 500 30-day implied vol, as market-wide stress.

Each reading comes with its own 30-day median, so callers compare implied vol with its usual level
(like for like) rather than with one instrument's realised vol. Any failure returns None; callers
fall back to realised volatility only. Nothing here can block trading.
"""

from __future__ import annotations

import logging
import statistics
import time
from typing import Any

import requests

from .brokers.base import asset_class_of
from .models import AssetClass

log = logging.getLogger("hermes_trader.vol")

DERIBIT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
VIX_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
DVOL_CURRENCIES = ("BTC", "ETH")


class ImpliedVol:
    def __init__(self, ttl_s: int = 1800, session: requests.Session | None = None, timeout: int = 5) -> None:
        self.ttl = ttl_s
        self.s = session or requests.Session()
        self.timeout = timeout
        self._cache: dict[str, tuple[float, tuple[float, float] | None]] = {}

    def for_symbol(self, symbol: str) -> tuple[float, float, str] | None:
        """(latest implied vol %, its 30-day median %, source) or None when there is no feed for it."""
        if asset_class_of(symbol) == AssetClass.CRYPTO:
            base = symbol.split("/")[0].upper()
            if base in DVOL_CURRENCIES:
                v = self._cached(f"dvol:{base}", lambda: self._dvol(base))
                return (v[0], v[1], f"Deribit DVOL {base}") if v else None
            return None
        v = self._cached("vix", self._vix)
        return (v[0], v[1], "CBOE VIX (S&P 500)") if v else None

    def _cached(self, key: str, fn: Any) -> tuple[float, float] | None:
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001 - optional data
            log.info("implied vol %s unavailable: %s", key, e)
            v = None
        self._cache[key] = (now, v)
        return v

    def _dvol(self, currency: str) -> tuple[float, float] | None:
        end = int(time.time() * 1000)
        r = self.s.get(DERIBIT, params={"currency": currency, "start_timestamp": end - 31 * 86_400_000,
                                        "end_timestamp": end, "resolution": "43200"}, timeout=self.timeout)
        r.raise_for_status()
        rows = sorted((r.json().get("result") or {}).get("data") or [], key=lambda x: x[0])
        closes = [float(x[4]) for x in rows if x and x[4] is not None]
        if not closes:
            return None
        scale = 100 if max(closes) < 3 else 1  # docs samples show fractions; the live index is in %
        return closes[-1] * scale, statistics.median(closes) * scale

    def _vix(self) -> tuple[float, float] | None:
        r = self.s.get(VIX_CSV, timeout=self.timeout)
        r.raise_for_status()
        lines = [x for x in r.text.strip().splitlines() if x.strip()]
        head = [h.strip().upper() for h in lines[0].split(",")]
        i = head.index("CLOSE")
        closes = [float(x.split(",")[i]) for x in lines[1:][-22:]]  # ~a month of sessions
        return (closes[-1], statistics.median(closes)) if closes else None
