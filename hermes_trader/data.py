"""Market-data sources for paper trading and backtests.

- SyntheticData: deterministic regime-switching random walk (offline, no keys).
  The bar at a given timestamp is always the same, so a paper "live" loop
  advances naturally with the clock.
- CSVData: your own history files: <dir>/<SYMBOL with / -> ->_<tf>.csv with
  columns ts,open,high,low,close,volume (ts = ISO date or epoch ms).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import timeframe_seconds
from .brokers.base import OHLCV_COLS

_ANCHOR = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
_MAX_BARS = 300_000


def _seed(symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:8], "little")


class SyntheticData:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now
        self._cache: dict[tuple[str, str, int], pd.DataFrame] = {}

    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def _series(self, symbol: str, timeframe: str) -> pd.DataFrame:
        step = timeframe_seconds(timeframe)
        now_ts = int(self.now().timestamp())
        last_closed = (now_ts // step) * step - step  # last fully closed bar open-time
        anchor = _ANCHOR
        n = (last_closed - anchor) // step + 1
        if n > _MAX_BARS:
            block = 100_000 * step
            anchor = ((last_closed - _MAX_BARS * step) // block) * block
            n = (last_closed - anchor) // step + 1
        key = (symbol, timeframe, last_closed)
        if key in self._cache:
            return self._cache[key]

        # Random draws come in fixed-size chunks keyed by chunk number, so bar i is
        # identical no matter how many bars are requested (timestamp-deterministic).
        chunk = 4096
        k = -(-n // chunk)
        draws = []
        for j in range(k):
            g = np.random.default_rng([_seed(symbol) % 2**63, step, anchor, j])
            draws.append((g.random(chunk), g.integers(0, 3, chunk), g.standard_t(5, chunk),
                          g.normal(0, 1, (2, chunk))))
        u = np.concatenate([d[0] for d in draws])[:n]
        switch_to = np.concatenate([d[1] for d in draws])[:n]
        noise = np.concatenate([d[2] for d in draws])[:n]
        wig_raw = np.concatenate([d[3] for d in draws], axis=1)[:, :n]

        scale = np.sqrt(step / 3600)
        base_vol = 0.006 * scale
        # Markov regimes: 0 chop, 1 up-trend, 2 down-trend
        drifts = np.array([0.0, 0.0006, -0.0006]) * (step / 3600)
        vols = np.array([1.0, 0.8, 1.3]) * base_vol
        stay = 0.995 if step <= 3600 else 0.97
        regime = np.empty(n, dtype=np.int8)
        r = 0
        for i in range(n):  # n is at most a few hundred thousand: fine
            if u[i] > stay:
                r = switch_to[i]
            regime[i] = r
        rets = drifts[regime] + vols[regime] * noise / np.sqrt(5 / 3)
        start = 100.0 + (_seed(symbol) % 50_000)
        close = start * np.exp(np.cumsum(rets))
        open_ = np.concatenate([[start], close[:-1]])
        wig = np.abs(wig_raw * base_vol * 0.6)
        high = np.maximum(open_, close) * (1 + wig[0])
        low = np.minimum(open_, close) * (1 - wig[1])
        vol = np.exp(10 + 0.5 * wig_raw[1])
        idx = pd.DatetimeIndex(pd.to_datetime(anchor + np.arange(n) * step, unit="s", utc=True), name="ts")
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
        self._cache = {key: df}
        return df

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return self._series(symbol, timeframe).tail(limit).copy()

    def last_price(self, symbol: str) -> float:
        return float(self._series(symbol, "1h")["close"].iloc[-1])


class CSVData:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)

    def path(self, symbol: str, timeframe: str) -> Path:
        return self.dir / f"{symbol.replace('/', '-')}_{timeframe}.csv"

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        p = self.path(symbol, timeframe)
        if not p.is_file():
            raise FileNotFoundError(f"no CSV for {symbol} {timeframe}: expected {p}")
        df = pd.read_csv(p)
        ts = df.pop("ts")
        unit = "ms" if pd.api.types.is_numeric_dtype(ts) else None
        df.index = pd.DatetimeIndex(pd.to_datetime(ts, unit=unit, utc=True), name="ts")
        return df[OHLCV_COLS].astype(float).sort_index().tail(limit)

    def last_price(self, symbol: str) -> float:
        files = sorted(self.dir.glob(f"{symbol.replace('/', '-')}_*.csv"))
        if not files:
            raise FileNotFoundError(f"no CSV for {symbol}")
        return float(pd.read_csv(files[0])["close"].iloc[-1])


def save_csv(df: pd.DataFrame, directory: str | Path, symbol: str, timeframe: str) -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{symbol.replace('/', '-')}_{timeframe}.csv"
    out = df[OHLCV_COLS].copy()
    out.index = out.index.map(lambda t: t.isoformat())
    out.index.name = "ts"
    out.to_csv(p)
    return p
