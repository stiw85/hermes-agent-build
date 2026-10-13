"""Key levels, BSM volatility maths, entry filters (shadow vs act), history replay."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from hermes_trader import context as cx
from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import DEFAULTS, load_config
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine
from hermes_trader.filters import EntryFilters, evaluate_history, filter_report
from hermes_trader.strategies import make

from .conftest import make_df

RISK = DEFAULTS["risk"]


def frame(closes, highs=None, lows=None, freq="1D"):
    c = np.asarray(closes, float)
    idx = pd.date_range("2026-01-01", periods=len(c), freq=freq, tz="UTC")
    return pd.DataFrame({"open": c, "high": c + 0.5 if highs is None else highs,
                         "low": c - 0.5 if lows is None else lows, "close": c, "volume": 1.0}, index=idx)


# ---- BSM maths ---------------------------------------------------------------------------------

def test_expected_move_and_probabilities():
    s_day = 0.55 / math.sqrt(365)  # 55% annual vol, daily bars
    em = cx.expected_move(60_000, s_day, 1)
    assert em["sigma_pct"] == pytest.approx(2.879, abs=0.01)  # the worked example: ~±2.9% a day
    assert em["band_1s"][1] == pytest.approx(60_000 * math.exp(0.02879), rel=1e-3)
    p_end = cx.p_finish_beyond(60_000, 63_000, s_day, 1)
    p_hit = cx.p_touch(60_000, 63_000, s_day, 1)
    assert 0.04 < p_end < 0.05 and p_hit == pytest.approx(2 * p_end, rel=0.05)  # reflection principle
    assert cx.p_finish_beyond(100, 100, 0.01, 10) == pytest.approx(0.5, abs=0.02)
    assert cx.p_touch(100, 100.0001, 0.01, 10) > 0.99
    assert cx.p_finish_beyond(100, 90, 0.01, 1) < 0.001  # 10% down in one 1% bar: essentially never


def test_stretch_z_sign():
    up = frame(np.linspace(100, 130, 60), freq="h")
    s = cx.sigma_per_bar(make_df(300))
    assert cx.stretch_z(up, 24, s) > 0
    assert cx.stretch_z(frame(np.linspace(130, 100, 60), freq="h"), 24, s) < 0


# ---- key levels --------------------------------------------------------------------------------

def test_round_step_and_pivots():
    assert cx.round_step(60_000) == 5_000 and cx.round_step(3_000) == 500 and cx.round_step(150) == 50
    assert cx.round_step(0.62) == pytest.approx(0.05)
    d = frame([10, 11, 12, 15, 12, 11, 10, 9, 8, 9, 10, 11, 12])
    hs, ls = cx.pivots(d, 3)
    assert hs == [15.5] and ls == [7.5]
    assert cx.pivots(d.iloc[:5], 3) == ([], [])  # the 15 high is not confirmed yet: no peeking


def test_key_levels_zones_and_nearest():
    # a swing high at ~110, a swing low at ~90, price now 100: resistance above, support below
    closes = [100, 102, 104, 106, 108, 110, 108, 104, 100, 96, 92, 90, 92, 96, 98, 100, 100, 100]
    d = frame(closes)
    lv = cx.key_levels(d, 100.0, pivot=3, round_numbers=False)
    sup, res = cx.nearest_levels(lv, 100.0, 0.5)
    assert res and res["price"] == pytest.approx(110.5, abs=0.6) and "daily swing high" in res["kinds"]
    assert sup and sup["price"] == pytest.approx(91.5, abs=0.1) and "prev week low" in sup["kinds"]  # nearer than the swing
    assert any(z["price"] == pytest.approx(89.5, abs=0.6) and "daily swing low" in z["kinds"] for z in lv)
    lv2 = cx.key_levels(d, 100.0, pivot=3, round_numbers=True)
    assert any("round number" in z["kinds"] for z in lv2)


# ---- filters -----------------------------------------------------------------------------------

def mk_filters(**over):
    c = {**DEFAULTS["filters"], **over}
    return EntryFilters(c, RISK)


def test_levels_filter_room():
    closes = [100, 102, 104, 106, 108, 110, 108, 104, 100, 96, 92, 90, 92, 96, 98, 100, 100, 100]
    d = frame(closes)
    hourly = make_df(300)
    f = mk_filters(levels={"enabled": True, "min_rr": 1.5, "pivot": 3, "round_numbers": False})
    # stop = 2 x ATR. ATR 2 -> stop 4; resistance ~110.5 is 10.5 away -> 2.6R: passes
    ok = f.check_levels(1, 100.0, hourly, 2.0, d)
    assert ok.passed and ok.value == pytest.approx(2.6, abs=0.2) and "resistance" in ok.note
    # ATR 5 -> stop 10 -> ~1.05R: too little room before resistance
    tight = f.check_levels(1, 100.0, hourly, 5.0, d)
    assert not tight.passed
    # shorts look down to support
    assert "support" in f.check_levels(-1, 100.0, hourly, 2.0, d).note
    # above every level: nothing in the way
    assert f.check_levels(1, 200.0, hourly, 2.0, d).note.startswith("open air")


def test_stretch_filter_blocks_chasing_only_in_trade_direction():
    f = mk_filters()
    base = make_df(300, seed=1, trend=0.0, vol=0.01)
    c = base["close"].to_numpy().copy()
    c[-24:] = c[-25] * np.exp(np.linspace(0.01, 0.25, 24))  # a huge 24-bar rally
    rally = base.assign(close=c, high=c * 1.002, low=c * 0.998)
    long_ = f.check_stretch(1, rally)
    assert not long_.passed and long_.value > 2
    assert f.check_stretch(-1, rally).passed  # shorting into it is not "chasing"


class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def run(tmp_path, now, hours, filters=None, name="a"):
    over = {"home": str(tmp_path / name)}
    if filters is not None:
        over["filters"] = filters
    cfg = load_config(overrides=over)
    clock = Clock(now)
    broker = PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5)
    eng = Engine(cfg, broker)
    if filters is not None and filters.get("enabled", True):
        eng.filters = EntryFilters(cfg["filters"], cfg["risk"], broker, cfg["timeframe"])
    for h in range(hours):
        t = now + timedelta(hours=h)
        clock.set(t)
        eng.cycle(t)
    return eng


def fills_of(eng):
    return [(f["symbol"], f["side"], round(f["qty"], 9)) for f in reversed(eng.journal.recent_fills(1000))]


def test_shadow_changes_nothing_and_scores_checks(tmp_path, now):
    base = run(tmp_path, now, 150, name="base")
    shadow = run(tmp_path, now, 150, filters={"mode": "shadow", "horizon_bars": 6,
                                              "levels": {"min_rr": 50.0}, "stretch": {"max_z": 0.01}}, name="s")
    assert fills_of(base) and fills_of(base) == fills_of(shadow)
    rows = shadow.journal.filter_rows()
    assert {r["name"] for r in rows} == {"levels", "stretch"}
    assert all(r["applied"] == 0 for r in rows) and any(not r["passed"] for r in rows)
    assert any(r["resolved_ts"] for r in rows)
    d = shadow.journal.rows("SELECT risk_notes FROM decisions WHERE risk_notes LIKE '%would skip (shadow)%'")
    assert d
    rep = filter_report(rows, shadow.cfg["filters"])
    assert rep["filters"]["levels"]["checks"] > 0 and "recommendation" in rep["filters"]["levels"]


def test_act_mode_skips_failing_entries(tmp_path, now):
    eng = run(tmp_path, now, 150, filters={"mode": "act", "levels": {"min_rr": 1000.0}, "stretch": {"enabled": False}},
              name="act")
    buys = [f for f in eng.journal.recent_fills(1000) if f["side"] == "buy"]
    vetoed = eng.journal.rows("SELECT * FROM decisions WHERE action='vetoed by filters'")
    open_air = [r for r in eng.journal.filter_rows() if r["passed"]]
    assert vetoed
    assert len(buys) <= len(open_air)  # only entries with no level in the way could go through
    assert all(r["applied"] for r in eng.journal.filter_rows() if not r["passed"])


def test_filter_errors_never_stop_trading(tmp_path, now):
    base = run(tmp_path, now, 100, name="b2")

    class Boom(EntryFilters):
        def evaluate(self, *a, **k):
            raise RuntimeError("kaput")

    cfg = load_config(overrides={"home": str(tmp_path / "boom"), "filters": {"mode": "act"}})
    clock = Clock(now)
    broker = PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5)
    eng = Engine(cfg, broker)
    eng.filters = Boom(cfg["filters"], cfg["risk"], broker)
    for h in range(100):
        clock.set(now + timedelta(hours=h))
        eng.cycle(now + timedelta(hours=h))
    assert fills_of(base) == fills_of(eng)
    assert any(r["error"] for r in eng.journal.filter_rows())


def test_history_replay_has_no_lookahead():
    df = make_df(1600, seed=5, trend=0.0, vol=0.012)
    s = make("sma_cross", {"fast": 10, "slow": 30})
    f = mk_filters()
    full = evaluate_history(df, s.targets(df), f, 12, details=True)
    part = evaluate_history(df.iloc[:1200], s.targets(df.iloc[:1200]), f, 12, details=True)
    assert full["entries"] > 5
    a = {r["ts"]: (r["levels"]["passed"], r["stretch"]["passed"]) for r in full["entries_detail"]}
    b = {r["ts"]: (r["levels"]["passed"], r["stretch"]["passed"]) for r in part["entries_detail"]}
    shared = set(a) & set(b)
    assert len(shared) >= len(b) - 1 and all(a[k] == b[k] for k in shared)
    lv = full["filters"]["levels"]
    assert lv["blocked"]["n"] + lv["passed"]["n"] == full["entries"]


def test_price_context_facts():
    df = make_df(600, seed=2)
    c = cx.price_context(df, None)
    assert c["expected_move"]["band_1s"][0] < c["price"] < c["expected_move"]["band_1s"][1]
    assert "nearest_support" in c and isinstance(c["levels"], list)
