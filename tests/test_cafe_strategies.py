"""The Trading Cafe strategies: SID method, W/M, head & shoulders, supply & demand."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hermes_trader.strategies import make


def frame(closes, opens=None):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, float)
    idx = pd.date_range("2026-01-01", periods=len(c), freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.5, "low": np.minimum(o, c) - 0.5, "close": c,
                         "volume": 1.0}, index=idx)


def flip(df):
    """Mirror prices (200 - x): a long setup becomes the matching short setup."""
    return pd.DataFrame({"open": 200 - df["open"], "high": 200 - df["low"], "low": 200 - df["high"],
                         "close": 200 - df["close"], "volume": df["volume"]}, index=df.index)


def changes(t):
    d = t[t != t.shift()].iloc[1:]
    return [(t.index.get_loc(i), v) for i, v in d.items()]


def sid_path():
    rng = np.random.default_rng(0)
    return frame(list(100 + rng.normal(0, 0.4, 60)) + list(np.linspace(100, 84, 16)) + list(np.linspace(84.5, 97, 18)))


def w_path(extra=(110, 112, 114, 116, 118, 119)):
    return frame([118.0] * 30 + [118, 119, 121, 118, 114, 110, 106, 102, 100, 102, 104, 107, 105, 103, 101, 103, 105,
                                 108, *extra])


def hs_path():
    return frame([130.0] * 30 + [130, 131, 128, 124, 120, 116, 112, 110, 113, 116, 120, 117, 113, 109, 105, 102, 100,
                                 103, 107, 111, 115, 119, 121, 118, 115, 112, 111, 114, 117, 120, 123, 126, 129, 133,
                                 137, 141, 143, 145, 147])


def sd_path(touches=1):
    closes = list(100 + 0.3 * np.sin(np.arange(40)))
    opens = list(closes)
    closes += [100.0, 102.5, 104.5, 106.0, 105.0, 103.5, 102.2]
    opens += [101.0, 100.0, 102.5, 104.5, 106.0, 105.0, 103.5]  # 101->100 is the bearish base candle
    for _ in range(touches - 1):  # earlier touches that don't qualify as a rejection (close in lower half)
        closes += [101.6, 103.5]
        opens += [102.2, 101.6]
    closes += [102.4] + list(np.linspace(103, 110, 8))
    opens += [102.0, 102.4] + list(np.linspace(103, 110, 8))[:-1]
    df = frame(closes, opens)
    rej = len(closes) - 9
    df.iloc[rej, df.columns.get_loc("low")] = 101.0  # the rejection bar's wick dips into the zone
    for j in range(touches - 1):
        df.iloc[47 + 2 * j, df.columns.get_loc("low")] = 101.2  # touches the zone, closes in its lower half
        df.iloc[48 + 2 * j, df.columns.get_loc("low")] = 101.7  # the bounce stays above the zone
    return df, rej


def test_sid_method_entry_on_turn_exit_at_rsi_50():
    s = make("sid_method", {"trend_guard": 0})
    df = sid_path()
    assert changes(s.targets(df)) == [(77, 1.0), (85, 0.0)]  # bought the turn after RSI < 30; out at RSI 50
    pd.testing.assert_series_equal(s.targets(flip(df)), -s.targets(df), check_names=False)


def test_sid_trend_guard_blocks_fading_a_strong_trend():
    up = frame(list(np.linspace(50, 100, 260)) + list(np.linspace(100, 108, 12)) + [107, 106.5, 106.8, 106.2])
    assert (make("sid_method", {"trend_guard": 0}).targets(up) < 0).any()
    assert not (make("sid_method", {"trend_guard": 1}).targets(up) < 0).any()


def test_double_bottom_neckline_break_and_target():
    s = make("double_top_bottom", {"pivot": 2})
    df = w_path()
    assert changes(s.targets(df)) == [(47, 1.0), (52, 0.0)]  # neckline break at 108, 1R target ~117 reached
    pd.testing.assert_series_equal(s.targets(flip(df)), -s.targets(df), check_names=False)
    # 3R would project beyond the start of the impulse: the site says skip such trades
    assert (make("double_top_bottom", {"pivot": 2, "rr": 3.0}).targets(df) == 0).all()


def test_head_and_shoulders_measured_move():
    s = make("head_shoulders", {"pivot": 2})
    df = hs_path()
    assert changes(s.targets(df)) == [(60, 1.0), (67, 0.0)]  # neckline break at 123; measured target ~143
    pd.testing.assert_series_equal(s.targets(flip(df)), -s.targets(df), check_names=False)
    # a "head" no deeper than the shoulders is a triple bottom, not H&S
    assert (make("head_shoulders", {"pivot": 2, "head_min": 0.9}).targets(df) == 0).all()


def test_supply_demand_first_touches_only():
    s = make("supply_demand", {"trend": 0, "lookback": 20, "impulse_atr": 2.0, "rr": 2.0})
    df, rej = sd_path()
    t = s.targets(df)
    assert changes(t)[0] == (rej, 1.0) and t.iloc[-1] == 0.0  # rejection entry, 2R target taken
    pd.testing.assert_series_equal(s.targets(flip(df)), -t, check_names=False)
    df2, rej2 = sd_path(touches=2)
    assert s.targets(df2).iloc[rej2] == 1.0  # second touch still trades
    df3, rej3 = sd_path(touches=3)
    assert (s.targets(df3).iloc[: rej3 + 1] == 0).all()  # third touch: zone retired
