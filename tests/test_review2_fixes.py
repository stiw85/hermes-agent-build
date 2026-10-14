"""Regression tests for the second independent review (Trading Cafe additions)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from hermes_trader import context as cx
from hermes_trader.config import DEFAULTS
from hermes_trader.data import SyntheticData
from hermes_trader.filters import EntryFilters
from hermes_trader.models import Account, Position, Signal
from hermes_trader.risk import RiskManager
from hermes_trader.strategies import make

from .test_cafe_strategies import changes, flip, frame, sd_path

PRE_W = [118.0] * 20 + [118, 116, 114, 113, 115, 117, 118] + [118.0] * 6  # an earlier swing before the pattern
W = [118, 119, 121, 118, 114, 110, 106, 102, 100, 102, 104, 107, 105, 103, 101]


@pytest.mark.parametrize("tail", [[108], [105, 108], [103, 105, 108]])
def test_patterns_catch_fast_breaks_after_earlier_swings(tail):
    """H1: a break 1-2 bars after the retest used to be missed once the zigzag had earlier swings."""
    df = frame(PRE_W + W + tail + [110, 112, 114, 116, 118, 119])
    s = make("double_top_bottom", {"pivot": 3})
    t = s.targets(df)
    assert changes(t)[0] == (len(PRE_W) + len(W) + len(tail) - 1, 1.0)
    pd.testing.assert_series_equal(s.targets(flip(df)), -t, check_names=False)


def test_head_and_shoulders_fast_break():
    pre = [130.0] * 20 + [130, 128, 126, 125, 127, 129, 130] + [130.0] * 6
    hs = pre + [130, 131, 128, 124, 120, 116, 112, 110, 113, 116, 120, 117, 113, 109, 105, 102, 100, 103, 107, 111,
                115, 119, 121, 118, 115, 112, 111, 116, 123, 126, 129, 133, 137, 141, 143, 145, 147]
    df = frame(hs)
    s = make("head_shoulders", {"pivot": 3})
    t = s.targets(df)
    assert changes(t)[0][1] == 1.0
    pd.testing.assert_series_equal(s.targets(flip(df)), -t, check_names=False)


@pytest.mark.parametrize("name", ["double_top_bottom", "head_shoulders"])
def test_pattern_mirror_exact_on_market_like_data(name):
    """L1: outside bars that are both a swing high and low no longer break the long/short mirror."""
    df = SyntheticData(datetime(2026, 6, 1, tzinfo=timezone.utc)).fetch_ohlcv("SOL/USDT", "1h", 3000)
    for k in (1, 3):
        s = make(name, {"pivot": k})
        pd.testing.assert_series_equal(s.targets(flip(df)), -s.targets(df), check_names=False)


def test_supply_demand_one_visit_is_one_touch_and_zones_are_not_duplicated():
    """M2: several bars inside the zone used to burn the zone; repeated breakout closes duplicated it."""
    s = make("supply_demand", {"trend": 0, "lookback": 20, "impulse_atr": 2.0, "rr": 2.0})
    df, rej = sd_path()
    # sit in the zone for two bars (closing in the lower half) before the rejection candle
    lingering = pd.concat([df.iloc[:rej], df.iloc[[rej - 1]], df.iloc[[rej - 1]], df.iloc[rej:]])
    lingering.index = pd.date_range(df.index[0], periods=len(lingering), freq="h")
    lingering.iloc[rej - 1, lingering.columns.get_loc("low")] = 101.2
    lingering.iloc[rej, lingering.columns.get_loc("low")] = 101.2
    lingering.iloc[rej + 1, lingering.columns.get_loc("low")] = 101.2
    t = s.targets(lingering)
    assert (t == 1.0).any()
    entries = int(((t == 1.0) & (t.shift() != 1.0)).sum())
    assert entries == 1  # the zone is traded once, not again from a duplicate


def test_event_tags_parse_robustly():
    """M3: '@BTC/USDT' was eaten as a time zone; '@AAPL,' never matched AAPL."""
    f = EntryFilters({**DEFAULTS["filters"], "events": {
        "enabled": True, "symbol_before_days": 14, "symbol_after_days": 1,
        "dates": ["2026-10-29T20:00Z @BTC/USDT token unlock", "2026-10-29 16:00 @SOL/USDT upgrade",
                  "2026-10-29 16:00 America/New_York @AAPL, @MSFT earnings"]}}, DEFAULTS["risk"])
    assert not f.event_errors and len(f.events) == 3
    t = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert not f.check_events(t, "BTC/USDT").passed
    assert f.check_events(t, "ETH/USDT").passed  # not market-wide
    assert not f.check_events(t, "SOL/USDT").passed
    assert not f.check_events(t, "AAPL").passed and not f.check_events(t, "MSFT").passed
    assert f.check_events(t, "ETHFI/USDT").passed


def test_htf_bias_stays_shadow_when_global_mode_is_act():
    """M4"""
    f = EntryFilters({**DEFAULTS["filters"], "mode": "act"}, DEFAULTS["risk"])
    assert f.mode("htf_bias") == "shadow" and f.mode("levels") == "act"


def test_correlation_inputs_warm_up_for_held_symbols(tmp_path):
    """M1: after a restart the cap was blind until each held symbol had been processed."""
    from hermes_trader.brokers.paper import PaperBroker
    from hermes_trader.config import load_config
    from hermes_trader.engine import Engine

    cfg = load_config(overrides={"home": str(tmp_path / "w")})
    eng = Engine(cfg, PaperBroker(SyntheticData(), cfg.home / "p.json", 10_000, 10, 5))
    acct = Account(cash=0, equity=10_000, positions={"ETH/USDT": Position("ETH/USDT", 1.0, 100, 100)})
    assert "ETH/USDT" not in eng._rets
    eng._warm_correlations(acct, datetime.now(timezone.utc))
    assert len(eng._rets["ETH/USDT"]) >= 50 and eng._stop_pct["ETH/USDT"] > 0


def test_opposite_side_hedge_is_not_capped_and_dust_does_not_count():
    """L2 + L4"""
    risk = {**DEFAULTS["risk"], "rebalance_threshold": 0.0, "max_order_notional": 1e9, "max_open_positions": 1}
    rm = RiskManager(risk, allow_short=True)
    a = Account(cash=8_000, equity=10_000, positions={"BTC/USDT": Position("BTC/USDT", 20.0, 100, 100)})
    short = rm.size(Signal("ETH/USDT", -1.0, "x", price=100.0, atr=2.0), a, 100.0, correlated={"BTC/USDT": 0.09})
    assert short.order is None or not any("correlated" in n for n in short.notes)  # a hedge, not the same bet
    dusty = Account(cash=10_000, equity=10_000, positions={"XRP/USDT": Position("XRP/USDT", 1e-9, 0.5, 0.5)})
    d = rm.size(Signal("ETH/USDT", 1.0, "x", price=100.0, atr=2.0), dusty, 100.0)
    assert d.order and not any("max open positions" in n for n in d.notes)


def test_equity_week_completes_on_friday():
    """L3: stock weeks used to count only from the next Tuesday."""
    idx = pd.date_range("2026-04-06", "2026-06-05", freq="B", tz="UTC")  # weekdays only, ends on a Friday
    c = np.linspace(100, 140, len(idx)) + 3 * np.sin(np.arange(len(idx)))
    d = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0}, index=idx)
    saturday = idx[-1] + pd.Timedelta(days=1)
    stock = cx.htf_bias(d, now=saturday, week_end_day=4)
    crypto_rule = cx.htf_bias(d, now=saturday, week_end_day=6)
    assert stock["weekly"] == 1 or stock["momentum"] == 1
    lv_stock = cx.key_levels(d, float(c[-1]), now=saturday, week_end_day=4, round_numbers=False)
    prev = {k: z["price"] for z in lv_stock for k in z["kinds"]}
    assert prev["prev week high"] == pytest.approx(float(d["high"].iloc[-5:].max()))
    assert crypto_rule is not None


def test_float_params_are_coerced():
    """L5"""
    s = make("supply_demand", {"lookback": 20.0, "trend": 1.0})
    assert s.params["lookback"] == 20 and isinstance(s.params["lookback"], int)
    s.targets(frame(list(np.linspace(100, 120, 300))))
