"""Regression tests for the independent review's confirmed findings."""

from __future__ import annotations

from datetime import timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import DEFAULTS, load_config
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine
from hermes_trader.filters import EntryFilters, evaluate_history
from hermes_trader.models import Order, Side
from hermes_trader.risk import RiskDecision
from hermes_trader.strategies import Strategy, make

from .conftest import make_df
from .test_orderflow import _abs_path

UTC = timezone.utc


class Const(Strategy):
    name = "const"
    defaults: dict = {"t": 1.0}

    def targets(self, df):
        return pd.Series(float(self.params["t"]), index=df.index)


class FlowConst(Const):
    name = "flow_const"
    needs_flow = True


class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def engine(tmp_path, now, filters=None, allow_short=True, name="e"):
    over = {"home": str(tmp_path / name), "allow_short": allow_short, "symbols": ["BTC/USDT"],
            "risk": {**DEFAULTS["risk"], "rebalance_threshold": 0.0, "max_order_notional": 1e9}}
    if filters is not None:
        over["filters"] = filters
    cfg = load_config(overrides=over)
    clock = Clock(now)
    eng = Engine(cfg, PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5))
    if filters is not None:
        eng.filters = EntryFilters(cfg["filters"], cfg["risk"], eng.broker, cfg["timeframe"])
    return eng, clock


def qty(eng):
    p = eng.broker.account(eng.symbols).positions.get("BTC/USDT")
    return p.qty if p else 0.0


def test_flip_closes_the_old_position_even_when_filters_skip_new_risk(tmp_path, now):
    """Review HIGH 1: an act-mode filter used to veto the whole flip order, leaving the long open."""
    off = {k: {"enabled": False} for k in ("levels", "stretch", "flow", "vol", "htf_bias")}
    blackout = {"mode": "act", **off, "events": {"enabled": True, "before_minutes": 600, "after_minutes": 600,
                                                 "dates": [f"{now:%Y-%m-%d %H:%M} UTC test-event"]}}
    eng, _ = engine(tmp_path, now, blackout)
    eng.book.strategy_for = lambda s: Const(t=1.0)
    eng.filters = None  # get into a long first
    eng.cycle(now)
    assert qty(eng) > 0
    eng.filters = EntryFilters(eng.cfg["filters"], eng.cfg["risk"], eng.broker, eng.cfg["timeframe"])
    eng.book.strategy_for = lambda s: Const(t=-1.0)
    eng.cycle(now + timedelta(minutes=1))
    assert qty(eng) == pytest.approx(0.0, abs=1e-12), "the long must be closed; only the new short is skipped"
    d = eng.journal.rows("SELECT * FROM decisions ORDER BY id DESC LIMIT 1")[0]
    assert d["action"].startswith("sell") and "new side of the flip skipped" in d["risk_notes"]


def test_flip_reduce_keeps_full_close(tmp_path, now):
    eng, _ = engine(tmp_path, now, {"mode": "act"})
    pos = type("P", (), {"qty": 2.0})()
    dec = RiskDecision(Order("BTC/USDT", Side.SELL, 5.0), True, [], -300.0, 200.0)  # close 2, open 3 short
    eng._scale_new_risk(dec, 0.5, pos, 100.0)
    assert dec.order.qty == pytest.approx(2.0 + 1.5)
    dec2 = RiskDecision(Order("BTC/USDT", Side.BUY, 4.0), True, [], 400.0, 0.0)  # pure new risk
    eng._scale_new_risk(dec2, 0.0, None, 100.0)
    assert dec2.order is None


def test_shadow_filter_verdicts_are_not_shown_to_the_llm(tmp_path, now):
    """Review HIGH 2: shadow notes reached the LLM reviewer via risk_notes."""
    eng, clock = engine(tmp_path, now, {"mode": "shadow", "levels": {"min_rr": 1000.0}})
    seen = []
    eng.reviewer = lambda sig, dec, acct, df: seen.append(list(dec.notes)) or {"verdict": "approve"}
    for h in range(60):
        clock.set(now + timedelta(hours=h))
        eng.cycle(now + timedelta(hours=h))
    assert seen, "reviewer never called"
    assert not any("shadow" in n or n.startswith("levels:") for notes in seen for n in notes)
    assert eng.journal.rows("SELECT * FROM decisions WHERE risk_notes LIKE '%would skip (shadow)%'")


def test_flow_strategy_holds_when_order_flow_is_missing(tmp_path, now):
    """Review HIGH 3: missing taker volume used to flatten flow_reversal positions."""
    eng, _ = engine(tmp_path, now, allow_short=False)
    eng.book.strategy_for = lambda s: Const(t=1.0)
    eng.cycle(now)
    held = qty(eng)
    assert held > 0
    eng.book.strategy_for = lambda s: FlowConst(t=0.0)  # would exit... if it could see order flow
    real = eng.broker.fetch_ohlcv
    eng.broker.fetch_ohlcv = lambda *a, **k: real(*a, **k).drop(columns="taker_buy")
    eng.cycle(now + timedelta(hours=1))
    assert qty(eng) == pytest.approx(held)
    d = eng.journal.rows("SELECT * FROM decisions ORDER BY id DESC LIMIT 1")[0]
    assert "no order-flow data" in d["risk_notes"]


def test_flow_reversal_decides_per_bar():
    df, a = _abs_path()
    s = make("flow_reversal", {"zone_bars": 48, "zone_atr": 1.0, "absorb": 0.15, "cvd": 0})
    t = s.targets(df)
    col = df.columns.get_loc("taker_buy")
    mid = df.copy()
    mid.iloc[a + 3, col] = np.nan  # a missing reading mid-trade: position kept, exits by price still work
    pd.testing.assert_series_equal(s.targets(mid), t, check_names=False)
    entry = df.copy()
    entry.iloc[a + 1, col] = np.nan  # no flow on the initiation bar: no entry on it
    t3 = s.targets(entry)
    assert t.iloc[a + 1] == 1.0 and t3.iloc[a + 1] == 0.0
    pd.testing.assert_series_equal(t3.iloc[: a + 1], t.iloc[: a + 1], check_names=False)


def test_bad_filter_config_never_stops_trading(tmp_path, now):
    """Review MEDIUM-HIGH 4: filters.horizon_bars: null made every symbol error every cycle."""
    eng, _ = engine(tmp_path, now, {"mode": "shadow", "horizon_bars": None})
    eng.book.strategy_for = lambda s: Const(t=1.0)
    rep = eng.cycle(now)
    assert "error" not in rep["symbols"]["BTC/USDT"] and qty(eng) > 0


def test_coin_m_klines_use_base_asset_volume():
    from hermes_trader.brokers.ccxt_broker import CCXTBroker

    class Coin:
        timeframes = {"1h": "1h"}
        now = 1_800_000_000_000 - (1_800_000_000_000 % 3_600_000)

        def load_markets(self):
            return {"BTC/USD:BTC": {"inverse": True, "id": "BTCUSD_PERP"}}

        def milliseconds(self):
            return self.now

        def dapiPublicGetKlines(self, params):  # noqa: N802
            return [[self.now - (3 - i) * 3_600_000, "1", "2", "0.5", "1.5", "999", 0, "7", 3, "555", "4", "0"]
                    for i in range(3)]

    df = CCXTBroker("binancecoinm", client=Coin()).fetch_ohlcv("BTC/USD:BTC", "1h", 3)
    assert (df["volume"] == 7.0).all() and (df["taker_buy"] == 4.0).all()


def test_replay_counts_reduce_filters_as_partial():
    df = make_df(1500, seed=7, trend=0.0, vol=0.012)
    s = make("sma_cross", {"fast": 10, "slow": 30})
    c = {**DEFAULTS["filters"], **{k: {"enabled": False} for k in ("levels", "stretch", "flow", "events", "htf_bias")},
         "vol": {"enabled": True, "max_expansion": 0.0, "iv": False, "reduce_to": 0.5}}
    out = evaluate_history(df, s.targets(df), EntryFilters(c, DEFAULTS["risk"]), 12)
    v = out["filters"]["vol"]
    assert v["passed"]["n"] == 0 and v["pnl_if_acting_pct"] == pytest.approx(v["pnl_without_pct"] * 0.5, rel=1e-6)


def test_key_levels_survive_nan_price():
    from hermes_trader import context as cx

    d = make_df(60, freq="1D")
    assert cx.key_levels(d, float("nan")) == [] and cx.price_context(d.iloc[:0], None) == {}
