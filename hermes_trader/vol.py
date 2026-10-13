"""Implied volatility feeds (the options market's own forecast of movement), cached, best effort.

- Crypto BTC/ETH: Deribit DVOL index (public, no key): 30-day implied vol, annualised %.
- US equities:    CBOE VIX daily history CSV (public): S&P 500 30-day implied vol, as market-wide stress.

Any failure returns None; callers fall back to realised volatility only. Nothing here can block trading.
"""

from __future__ import annotations

import logging
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
    def __init__(self, ttl_s: int = 1800, session: requests.Session | None = None, timeout: int = 10) -> None:
        self.ttl = ttl_s
        self.s = session or requests.Session()
        self.timeout = timeout
        self._cache: dict[str, tuple[float, float | None]] = {}

    def for_symbol(self, symbol: str) -> tuple[float, str] | None:
        """(implied vol in annualised %, source label) or None when there is no feed for it."""
        if asset_class_of(symbol) == AssetClass.CRYPTO:
            base = symbol.split("/")[0].upper()
            if base in DVOL_CURRENCIES:
                v = self._cached(f"dvol:{base}", lambda: self._dvol(base))
                return (v, f"Deribit DVOL {base}") if v else None
            return None
        v = self._cached("vix", self._vix)
        return (v, "CBOE VIX") if v else None

    def _cached(self, key: str, fn: Any) -> float | None:
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

    def _dvol(self, currency: str) -> float | None:
        end = int(time.time() * 1000)
        r = self.s.get(DERIBIT, params={"currency": currency, "start_timestamp": end - 2 * 86_400_000,
                                        "end_timestamp": end, "resolution": "3600"}, timeout=self.timeout)
        r.raise_for_status()
        rows = (r.json().get("result") or {}).get("data") or []
        if not rows:
            return None
        last = max(rows, key=lambda x: x[0])
        v = float(last[4])
        return v * 100 if v < 3 else v  # docs samples show fractions; the live index is in %

    def _vix(self) -> float | None:
        r = self.s.get(VIX_CSV, timeout=self.timeout)
        r.raise_for_status()
        lines = [x for x in r.text.strip().splitlines() if x.strip()]
        head = [h.strip().upper() for h in lines[0].split(",")]
        last = lines[-1].split(",")
        return float(last[head.index("CLOSE")])
