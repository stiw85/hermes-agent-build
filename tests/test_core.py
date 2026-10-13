"""Indicators, strategies (no look-ahead), backtester, risk manager."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hermes_trader import indicators as ind
from hermes_trader.backtest import backtest, periods_per_year, timeframe_seconds
from hermes_trader.models import Account, Position, Side, Signal
from hermes_trader.risk import RiskManager, RiskState
from hermes_trader.strategies import REGISTRY, Strategy, make

from .conftest import make_df


def test_indicators_basic(df):
    s = ind.sma(df["close"], 10)
    assert s.iloc[:9].isna().all()
    assert s.iloc[9] == pytest.approx(df["close"].iloc[:10].mean())
    r = ind.rsi(df["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert ind.rsi(up).iloc[-1] == 100.0
    assert (ind.atr(df).dropna() > 0).all()
    lo, mid, hi = ind.bollinger(df["close"])
    assert (lo.dropna() <= hi.dropna()).all()


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_strategies_have_no_lookahead(name):
    """Target at bar t must not change when future bars are appended."""
    df = make_df(700, seed=3, trend=0.0, vol=0.015)
    strat = make(name)
    full = strat.targets(df).fillna(0)
    part = strat.targets(df.iloc[:500]).fillna(0)
    pd.testing.assert_series_equal(full.iloc[:500], part, check_names=False)
    assert full.between(-1, 1).all()


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_param_space_valid(name):
    space = REGISTRY[name].param_space()
    assert space
    for p in space:
        assert REGISTRY[name].valid(p)


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        make("sma_cross", {"fast": 50, "slow": 20})
    with pytest.raises(ValueError):
        make("sma_cross", {"nope": 1})


class AlwaysLong(Strategy):
    name = "always_long"
    defaults: dict = {}

    def targets(self, df):
        return pd.Series(1.0, index=df.index)


def test_backtest_costs_and_alignment():
    df = make_df(300, seed=5)
    r0 = backtest(df, AlwaysLong(), fee_bps=0, slippage_bps=0)
    # position from bar 1 onward: equals close[-1]/close[0]
    assert r0.total_return == pytest.approx(df["close"].iloc[-1] / df["close"].iloc[0] - 1, rel=1e-9)
    r1 = backtest(df, AlwaysLong(), fee_bps=10, slippage_bps=5)
    assert r1.total_return < r0.total_return
    assert r1.fees_paid_pct == pytest.approx(0.0015)
    assert r1.trades == 1


def test_drawdown_counts_from_initial_capital():
    df = make_df(10, vol=0.0, trend=0.0)
    df.loc[df.index[4]:, "close"] = 50.0  # -50% on the first scored bar
    r = backtest(df, AlwaysLong(), fee_bps=0, slippage_bps=0, eval_from=4)
    assert r.total_return == pytest.approx(-0.5)
    assert r.max_drawdown == pytest.approx(0.5)


def test_backtest_eval_from_only_scores_tail():
    df = make_df(400)
    r = backtest(df, make("sma_cross"), eval_from=300)
    assert r.bars == 100
    assert len(r.equity) == 100


def test_short_clipped_when_disabled():
    df = make_df(400, trend=-0.002)
    r_long_only = backtest(df, make("sma_cross"), allow_short=False)
    r_short = backtest(df, make("sma_cross"), allow_short=True)
    assert r_short.total_return > r_long_only.total_return


def test_timeframes():
    assert timeframe_seconds("15m") == 900
    assert timeframe_seconds("4h") == 14400
    assert periods_per_year("1d", "equity") == 252
    assert periods_per_year("1h", "crypto") == 8760
    assert math.isclose(periods_per_year("1h", "equity"), 1638)


# ---------------------------------------------------------------- risk
RISK = {"max_position_pct": 0.2, "max_gross_exposure_pct": 0.8, "max_order_notional": 2500,
        "min_order_notional": 10, "risk_per_trade_pct": 0.01, "atr_stop_mult": 2.0, "max_daily_loss_pct": 0.03,
        "max_drawdown_pct": 0.15, "rebalance_threshold": 0.1, "max_trades_per_day": 20}


def acct(cash=10_000.0, positions=None):
    positions = positions or {}
    eq = cash + sum(p.qty * p.market_price for p in positions.values())
    return Account(cash=cash, equity=eq, positions=positions)


def test_risk_sizes_to_max_position():
    rm = RiskManager(RISK)
    d = rm.size(Signal("BTC/USDT", 1.0, "x", price=100), acct(), 100.0)
    assert d.approved and d.order.side == Side.BUY
    assert d.order.qty * 100 == pytest.approx(2000)


def test_risk_atr_cap():
    rm = RiskManager(RISK)
    # 1% of 10k = 100 risk; stop = 2*ATR(10) = 20 per unit -> 5 units -> 500 notional
    d = rm.size(Signal("X", 1.0, "x", price=100, atr=10), acct(), 100.0)
    assert d.order.qty == pytest.approx(5)


def test_risk_order_cap_and_threshold():
    rm = RiskManager({**RISK, "max_order_notional": 500})
    d = rm.size(Signal("X", 1.0, "x"), acct(), 100.0)
    assert d.order.qty * 100 == pytest.approx(500)
    pos = {"X": Position("X", 19.5, 100, 100)}  # 1950 of 2000 target: below threshold
    d2 = rm.size(Signal("X", 1.0, "x"), acct(8050, pos), 100.0)
    assert d2.order is None


def test_risk_no_shorts_and_close():
    rm = RiskManager(RISK)
    assert rm.size(Signal("X", -1.0, "x"), acct(), 100.0).order is None
    pos = {"X": Position("X", 3.0, 100, 100)}
    d = rm.size(Signal("X", -1.0, "x"), acct(9700, pos), 100.0)
    assert d.order.side == Side.SELL and d.order.qty == pytest.approx(3.0)


def test_risk_gross_exposure():
    rm = RiskManager(RISK)
    pos = {s: Position(s, 19.0, 100, 100) for s in ("A", "B", "C", "D")}  # 7600 used of 8000 (eq=10000)
    d = rm.size(Signal("E", 1.0, "x"), acct(2400, pos), 100.0)
    assert d.order.qty * 100 == pytest.approx(400)


def test_breakers():
    rm = RiskManager(RISK)
    st = RiskState()
    rm.roll_day(st, "2026-01-01", 10_000)
    assert rm.breaker(st, 9_800)[0] == "ok"
    assert rm.breaker(st, 9_600)[0] == "reduce_only"
    assert rm.breaker(st, 8_400)[0] == "kill"
    # reduce-only blocks new risk but allows exits
    assert rm.size(Signal("X", 1.0, "x"), acct(9600), 100.0, "reduce_only").order is None
    pos = {"X": Position("X", 3.0, 100, 100)}
    assert rm.size(Signal("X", 0.0, "x"), acct(9300, pos), 100.0, "reduce_only").order.side == Side.SELL
    # kill flattens even if strategy says long
    assert rm.size(Signal("X", 1.0, "x"), acct(9300, pos), 100.0, "kill").order.side == Side.SELL


def test_kill_closes_dust():
    rm = RiskManager(RISK)
    pos = {"X": Position("X", 0.05, 100, 100)}  # $5 < min_order_notional
    d = rm.size(Signal("X", 1.0, "x"), acct(9995, pos), 100.0, "kill")
    assert d.order and d.order.side == Side.SELL and d.order.qty == pytest.approx(0.05)


def test_stop_hit():
    rm = RiskManager(RISK)
    assert rm.stop_hit(1, 100, 79, 10)
    assert not rm.stop_hit(1, 100, 81, 10)
    assert rm.stop_hit(-1, 100, 121, 10)
    assert not rm.stop_hit(0, 100, 50, 10)


def test_config_rejects_env_lines_without_echoing_secret(tmp_path):
    from hermes_trader.config import ConfigError, load_config

    p = tmp_path / "config.yaml"
    p.write_text("mode: paper\nLLM_API_KEY=sk-ant-SECRET123\nllm:\n  enabled: true\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    msg = str(e.value)
    assert "line 2 (LLM_API_KEY=...)" in msg and ".env" in msg and "SECRET" not in msg
    p.write_text("llm:\n  enabled: true\n model: x\n")  # bad indent
    with pytest.raises(ConfigError, match="line 3"):
        load_config(p)
