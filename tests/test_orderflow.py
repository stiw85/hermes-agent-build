"""Order flow: taker volume plumbing, delta/CVD, divergences, flow_reversal, flow filter."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from hermes_trader import indicators as ind
from hermes_trader.brokers.ccxt_broker import CCXTBroker
from hermes_trader.config import DEFAULTS
from hermes_trader.data import CSVData, SyntheticData, save_csv
from hermes_trader.filters import EntryFilters
from hermes_trader.strategies import make


def bars(closes, buy_share, opens=None, highs=None, lows=None, vol=100.0):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, float)
    idx = pd.date_range("2026-01-01", periods=len(c), freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.5 if highs is None else highs,
                         "low": np.minimum(o, c) - 0.5 if lows is None else lows, "close": c, "volume": vol,
                         "taker_buy": vol * np.asarray(buy_share, float)}, index=idx)


def test_delta_cvd_and_share():
    df = bars([1, 2, 3, 4], [0.75, 0.25, 0.5, 1.0])
    assert ind.delta(df).tolist() == [50, -50, 0, 100]
    assert ind.cvd(df).tolist() == [50, 0, 0, 100]
    assert ind.delta_share(df, 2).iloc[-1] == pytest.approx(0.5)
    assert ind.has_flow(df) and not ind.has_flow(df.drop(columns="taker_buy"))


def test_cvd_divergence_cases():
    n = 5
    # price makes a higher high while buying dries up -> bearish (buyers exhausted)
    up = list(np.linspace(100, 110, n)) + list(np.linspace(108, 112, n))
    share = [0.9] * n + [0.4] * n
    assert ind.cvd_divergence(bars(up, share), n).iloc[-1] == -1
    # price makes a lower low while selling dries up -> bullish (sellers exhausted)
    down = list(np.linspace(110, 100, n)) + list(np.linspace(102, 98, n))
    share2 = [0.1] * n + [0.6] * n
    assert ind.cvd_divergence(bars(down, share2), n).iloc[-1] == 1
    # flow agrees with price: no divergence
    assert ind.cvd_divergence(bars(up, [0.8] * (2 * n)), n).iloc[-1] == 0


def test_candle_delta_divergence():
    df = bars([100, 101, 100], [0.5, 0.2, 0.8], opens=[100, 100, 101])
    assert ind.candle_delta_divergence(df).tolist() == [0, 1, -1]


class FakeBinance:
    timeframes = {"1h": "1h"}

    def __init__(self, n=2500, fail=False):
        self.n, self.fail, self.calls = n, fail, 0
        self.now = 1_800_000_000_000 - (1_800_000_000_000 % 3_600_000)
        self.rows = [[self.now - (n - i) * 3_600_000, "1", "2", "0.5", str(1 + i % 7), "10", 0, "0", 5, str(i % 10),
                      "0", "0"] for i in range(n)]

    def load_markets(self):
        return {"BTC/USDT": {"spot": True, "id": "BTCUSDT"}}

    def milliseconds(self):
        return self.now

    def publicGetKlines(self, params):  # noqa: N802 - ccxt naming
        self.calls += 1
        if self.fail:
            raise RuntimeError("geo-blocked")
        assert params["symbol"] == "BTCUSDT" and params["interval"] == "1h"
        return [r for r in self.rows if r[0] >= params["startTime"]][: params["limit"]]

    def fetch_ohlcv(self, symbol, tf, since=None, limit=None):
        return [[r[0], 1.0, 2.0, 0.5, float(r[4]), 10.0] for r in self.rows][-(limit or 100):]


def test_binance_klines_carry_taker_volume_and_page():
    x = FakeBinance()
    b = CCXTBroker("binance", client=x)
    df = b.fetch_ohlcv("BTC/USDT", "1h", 2200)
    assert len(df) == 2200 and x.calls >= 3  # paged in 1000s
    assert "taker_buy" in df and df["taker_buy"].iloc[-1] == float(x.rows[-1][9])
    assert df.index.is_monotonic_increasing and not df.index.duplicated().any()


def test_klines_failure_falls_back_to_plain_ohlcv():
    b = CCXTBroker("binance", client=FakeBinance(fail=True))
    df = b.fetch_ohlcv("BTC/USDT", "1h", 50)
    assert len(df) == 50 and "taker_buy" not in df
    other = CCXTBroker("kraken", client=FakeBinance())
    assert "taker_buy" not in other.fetch_ohlcv("BTC/USDT", "1h", 10)


def test_synthetic_and_csv_carry_taker_volume(tmp_path):
    s = SyntheticData(datetime(2026, 6, 1, tzinfo=timezone.utc))
    df = s.fetch_ohlcv("BTC/USDT", "1h", 500)
    assert ind.has_flow(df)
    assert ((df["taker_buy"] > 0) & (df["taker_buy"] < df["volume"])).all()
    # aggression leans with the bar's direction
    up = df["close"] > df["open"]
    assert ind.delta(df)[up].mean() > 0 > ind.delta(df)[~up].mean()
    save_csv(df, tmp_path, "BTC/USDT", "1h")
    back = CSVData(tmp_path).fetch_ohlcv("BTC/USDT", "1h", 500)
    assert np.allclose(back["taker_buy"], df["taker_buy"])


def _abs_path():
    """Range, sell-off to a 48-bar low, absorption bar, initiation bar, rally to the prior high."""
    closes = list(100 + 3 * np.sin(np.arange(60) / 4)) + list(np.linspace(99, 95, 8))
    share = [0.5] * len(closes)
    opens = None
    a = len(closes)
    closes += [95.6]       # absorption: heavy net selling at the low, but closes in the upper half
    share += [0.2]
    closes += [96.6]       # initiation: clears the absorption bar's high with net buying
    share += [0.75]
    closes += list(np.linspace(97, 103.6, 8))
    share += [0.6] * 8
    o = np.concatenate([[closes[0]], closes[:-1]])
    h = np.maximum(o, closes) + 0.3
    lo = np.minimum(o, closes) - 0.3
    lo[a] = 94.4  # long lower wick into the zone
    return bars(closes, share, opens=opens, highs=h, lows=lo), a


def test_flow_reversal_absorption_then_initiation():
    s = make("flow_reversal", {"zone_bars": 48, "zone_atr": 1.0, "absorb": 0.15, "cvd": 0})
    df, a = _abs_path()
    t = s.targets(df)
    assert (t.iloc[: a + 1] == 0).all(), "absorption alone is not an entry"
    assert t.iloc[a + 1] == 1.0, "initiation bar enters"
    assert t.iloc[-1] == 0.0, "target (prior range high) takes profit"
    flipped = bars(200 - df["close"], 1 - df["taker_buy"] / df["volume"], opens=200 - df["open"],
                   highs=200 - df["low"], lows=200 - df["high"])
    pd.testing.assert_series_equal(s.targets(flipped), -t, check_names=False)


def test_flow_reversal_inactive_without_flow_and_no_lookahead():
    df, _ = _abs_path()
    assert (make("flow_reversal").targets(df.drop(columns="taker_buy")) == 0).all()
    syn = SyntheticData(datetime(2026, 6, 1, tzinfo=timezone.utc)).fetch_ohlcv("ETH/USDT", "1h", 1500)
    s = make("flow_reversal", {"zone_bars": 24, "zone_atr": 1.0, "absorb": 0.1, "cvd": 1})
    full, part = s.targets(syn), s.targets(syn.iloc[:1100])
    pd.testing.assert_series_equal(full.iloc[:1100], part, check_names=False)


def test_flow_filter():
    f = EntryFilters({**DEFAULTS["filters"], "flow": {"enabled": True, "bars": 5}}, DEFAULTS["risk"])
    n = 5
    up = list(np.linspace(100, 110, n)) + list(np.linspace(108, 112, n))
    df = bars(up, [0.9] * n + [0.4] * n)  # bearish divergence
    assert not f.check_flow(1, df).passed and "buyers exhausted" in f.check_flow(1, df).note
    assert f.check_flow(-1, df).passed
    assert f.check_flow(1, df.drop(columns="taker_buy")).note.startswith("no order-flow")
