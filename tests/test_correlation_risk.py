"""Max open positions + correlated risk cap (The Trading Cafe: <= 2% combined risk on correlated trades)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hermes_trader.config import DEFAULTS
from hermes_trader.models import Account, Position, Signal
from hermes_trader.risk import RiskManager

RISK = {**DEFAULTS["risk"], "rebalance_threshold": 0.0, "max_order_notional": 1e9}


def acct(**pos):
    ps = {s.replace("_", "/"): Position(s.replace("_", "/"), q, px, px) for s, (q, px) in pos.items()}
    held = sum(abs(p.qty * p.avg_price) for p in ps.values())
    return Account(cash=10_000 - held, equity=10_000, positions=ps)


def sig(sym, target, atr, price=100.0):
    return Signal(sym, target, "x", reason="r", price=price, atr=atr)


def test_correlated_cap_shrinks_new_correlated_risk():
    rm = RiskManager(RISK, allow_short=True)
    a = acct(BTC_USDT=(20.0, 100.0))  # 2,000 notional
    # BTC's stop is 9% away -> 180 of risk already used; cap 2% of 10k = 200 -> 20 left
    # ETH stop = 2 x 2 ATR / 100 = 4% -> at most 20 / 0.04 = 500 notional
    d = rm.size(sig("ETH/USDT", 1.0, 2.0), a, 100.0, correlated={"BTC/USDT": 0.09})
    assert d.order and d.order.qty * 100 == pytest.approx(500, rel=1e-6)
    assert any("correlated risk cap" in n for n in d.notes)
    # uncorrelated: normal size (ATR sizing: 1% / 4% = 2,500 -> capped by 20% position = 2,000)
    d2 = rm.size(sig("ETH/USDT", 1.0, 2.0), a, 100.0, correlated={})
    assert d2.order.qty * 100 == pytest.approx(2000, rel=1e-6)


def test_correlated_cap_never_forces_a_cut_or_blocks_an_exit():
    rm = RiskManager(RISK, allow_short=True)
    a = acct(BTC_USDT=(20.0, 100.0), ETH_USDT=(15.0, 100.0))
    hold = rm.size(sig("ETH/USDT", 1.0, 2.0), a, 100.0, correlated={"BTC/USDT": 0.09})
    assert hold.order is None or hold.order.side.value == "buy"  # never a forced sell
    assert hold.order is None  # already over the cap: no adding, but nothing sold either
    out = rm.size(sig("ETH/USDT", 0.0, 2.0), a, 100.0, correlated={"BTC/USDT": 0.09})
    assert out.order and out.order.side.value == "sell" and out.order.qty == pytest.approx(15.0)


def test_max_open_positions():
    rm = RiskManager({**RISK, "max_open_positions": 2}, allow_short=True)
    a = acct(BTC_USDT=(5.0, 100.0), ETH_USDT=(5.0, 100.0))
    new = rm.size(sig("SOL/USDT", 1.0, 2.0), a, 100.0)
    assert new.order is None and any("max open positions" in n for n in new.notes)
    more = rm.size(sig("BTC/USDT", 1.0, 2.0), a, 100.0)  # a symbol already held may still change
    assert more.order and more.order.side.value == "buy"


def test_engine_detects_correlated_positions(tmp_path):
    from hermes_trader.brokers.paper import PaperBroker
    from hermes_trader.config import load_config
    from hermes_trader.data import SyntheticData
    from hermes_trader.engine import Engine

    cfg = load_config(overrides={"home": str(tmp_path / "c")})
    eng = Engine(cfg, PaperBroker(SyntheticData(), cfg.home / "p.json", 10_000, 10, 5))
    idx = pd.date_range("2026-01-01", periods=301, freq="h", tz="UTC")
    rng = np.random.default_rng(3)
    base = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 301))), index=idx)
    noise = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 301))), index=idx)
    df = pd.DataFrame({"close": base})
    eng._rets["BTC/USDT"] = np.log(base * 1.0001).diff().dropna().tail(200)  # moves with ETH
    eng._rets["SOL/USDT"] = np.log(noise).diff().dropna().tail(200)  # independent
    eng._stop_pct["BTC/USDT"] = 0.05
    a = acct(BTC_USDT=(1.0, 100.0), SOL_USDT=(1.0, 100.0))
    got = eng._correlated("ETH/USDT", df, sig("ETH/USDT", 1.0, 2.0), 100.0, a)
    assert got == {"BTC/USDT": 0.05}
