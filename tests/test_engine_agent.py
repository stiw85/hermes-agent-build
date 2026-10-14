"""Engine cycles, kill switch, improver gates, strategy book, memory, LLM reviewer and agent loop."""

from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd
import pytest

from hermes_trader.agent import Agent, Lessons, Playbooks, Toolkit, make_reviewer, reflect
from hermes_trader.book import StrategyBook
from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine, closed_bars, review_multiplier
from hermes_trader.improve import Candidate, Improver
from hermes_trader.runtime import BUNDLED_PLAYBOOKS

from .conftest import FakeLLM, make_df


class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def build(cfg, now, data=None):
    data = data or Clock(now)
    broker = PaperBroker(data, cfg.home / "paper.json", 10_000, 10, 5)
    eng = Engine(cfg, broker)
    b = cfg["broker"]
    imp = Improver(cfg["improve"], fee_bps=b["fee_bps"], slippage_bps=b["slippage_bps"], timeframe="1h",
                   allow_short=False)
    tk = Toolkit(eng, imp, Lessons(cfg.home / "LESSONS.md"), Playbooks(cfg.home / "pb", [BUNDLED_PLAYBOOKS]))
    return eng, imp, tk, data


def test_closed_bars_drops_forming_candle(df):
    now = df.index[-1] + pd.Timedelta(minutes=30)
    assert len(closed_bars(df, "1h", now)) == len(df) - 1


def test_engine_runs_many_cycles(cfg, now):
    eng, _, _, clock = build(cfg, now)
    actions = []
    for h in range(120):
        clock.set(now + timedelta(hours=h))
        rep = eng.cycle(now + timedelta(hours=h))
        actions += [v["action"] for v in rep["symbols"].values()]
    fills = eng.journal.recent_fills(500)
    assert fills, "expected some trades over 120 hourly cycles"
    st = eng.status()
    assert st["equity"] > 0
    # position never exceeds 20% of equity (+ drift)
    for p in st["positions"].values():
        assert abs(p["qty"] * p["px"]) <= 0.2 * st["equity"] * 1.3
    assert eng.journal.stats()["fills"] == len(fills)


class CrashData:
    """Price falls 30% after the first cycle -> drawdown kill switch."""

    def __init__(self):
        self.mult = 1.0

    def fetch_ohlcv(self, s, tf, n):
        d = make_df(300, trend=0.003, vol=0.001)  # steady uptrend -> sma_cross long
        d.index = pd.date_range(end="2026-06-01 10:00", periods=300, freq="1h", tz="UTC", name="ts")
        return d * self.mult

    def last_price(self, s):
        return float(self.fetch_ohlcv(s, "1h", 300)["close"].iloc[-1])


def test_kill_switch_flattens_and_halts(cfg, now):
    cfg.raw["risk"]["max_position_pct"] = 0.8
    cfg.raw["risk"]["risk_per_trade_pct"] = 1.0
    cfg.raw["risk"]["max_order_notional"] = 100_000
    data = CrashData()
    eng, *_ = build(cfg, now, data)
    eng.cycle(now)
    assert eng.broker.account(eng.symbols).positions
    data.mult = 0.5
    rep = eng.cycle(now + timedelta(hours=1))
    assert rep["level"] == "kill" and eng.state.halted
    assert not eng.broker.account(eng.symbols).positions
    assert eng.journal.recent_events(kind="halt")
    # stays halted: no new entries even though signal is long
    data.mult = 0.6
    eng.cycle(now + timedelta(hours=2))
    assert not eng.broker.account(eng.symbols).positions
    eng.resume()
    assert not eng.state.halted


def test_book_promote_and_rollback(tmp_path):
    book = StrategyBook(tmp_path / "b.yaml", {"name": "sma_cross", "params": {"fast": 20, "slow": 50}})
    assert book.entry("X")["version"] == 0
    book.promote("X", "ema_cross", {"fast": 12, "slow": 26}, {}, "test")
    book.promote("X", "rsi_reversion", {"period": 14, "lower": 30, "upper": 70, "exit": 50}, {}, "test")
    assert StrategyBook(tmp_path / "b.yaml", {}).entry("X")["strategy"] == "rsi_reversion"
    rb = book.rollback("X")
    assert rb["strategy"] == "ema_cross"
    with pytest.raises(ValueError):
        book.promote("X", "sma_cross", {"fast": 99, "slow": 2}, {}, "bad")


def test_improver_gate(cfg):
    imp = Improver(cfg["improve"], fee_bps=10, slippage_bps=5, timeframe="1h", allow_short=False)
    t = {"trades": 20, "max_drawdown": 0.1, "sharpe": 1.5, "total_return": 0.1}
    good = Candidate("x", {}, {}, 1.0, t, 1.5)
    assert imp.gate(good, 1.0)[0]
    assert not imp.gate(good, 1.45)[0]  # not enough improvement
    assert imp.gate(good, -math.inf)[0]
    assert not imp.gate(Candidate("x", {}, {}, 1.0, {**t, "trades": 2}, 1.5), 0)[0]
    assert not imp.gate(Candidate("x", {}, {}, 1.0, {**t, "max_drawdown": 0.5}, 1.5), 0)[0]


def test_search_never_sees_holdout(cfg):
    imp = Improver(cfg["improve"], fee_bps=10, slippage_bps=5, timeframe="1h", allow_short=False)
    df = make_df(1500, seed=11, vol=0.012)
    garbage = df.copy()
    split = imp.split(df)
    garbage.iloc[split:] = garbage.iloc[split:] * 3.7  # wreck the holdout
    def fresh():  # same sampling seed for both runs
        return Improver(cfg["improve"], fee_bps=10, slippage_bps=5, timeframe="1h", allow_short=False)

    a = [(c.strategy, c.params, c.train_score) for c in fresh().search("X/USDT", df)]
    b = [(c.strategy, c.params, c.train_score) for c in fresh().search("X/USDT", garbage)]
    assert a
    assert a == b


def test_random_walks_rarely_promote(cfg, tmp_path):
    imp = Improver(cfg["improve"], fee_bps=10, slippage_bps=5, timeframe="1h", allow_short=False)
    promoted = 0
    for seed in range(12):
        book = StrategyBook(tmp_path / f"b{seed}.yaml", cfg["default_strategy"])
        df = make_df(2000, seed=100 + seed, trend=0.0, vol=0.01)
        promoted += imp.run("X/USDT", df, book, promote=True).promoted
    assert promoted <= 2, f"{promoted}/12 random walks promoted a strategy: gate is leaking"


def test_improver_runs_and_promotes_only_through_gate(cfg, now):
    eng, imp, _, _ = build(cfg, now)
    df = eng.broker.fetch_ohlcv("BTC/USDT", "1h", 1500)
    rep = imp.run("BTC/USDT", df, eng.book, promote=True)
    d = rep.to_dict()
    assert d["leaderboard"]
    if rep.promoted:
        assert eng.book.entry("BTC/USDT")["source"] == "walk-forward"
        assert rep.best.test["trades"] >= cfg["improve"]["min_trades"]
    else:
        assert eng.book.entry("BTC/USDT")["version"] == 0
    assert all("holdout" not in c for c in d["leaderboard"][1:])  # only the chosen challenger is tested


def test_stop_cooldown_survives_the_stop_cycle(cfg, now):
    data = CrashData()
    cfg.raw["risk"]["risk_per_trade_pct"] = 1.0
    eng, *_ = build(cfg, now, data)
    eng.cycle(now)
    assert eng.broker.account(eng.symbols).positions
    data.mult = 0.97  # small drop: below ATR stop, far from the kill switch
    eng.cycle(now + timedelta(hours=1))
    assert eng.journal.recent_events(kind="stop")
    assert eng.cooldown, "cooldown must persist after the stop fires"
    assert not eng.broker.account(eng.symbols).positions
    eng.state.trades_today = 0
    eng.state.start_of_day_equity = eng.broker.account(eng.symbols).equity
    eng.cycle(now + timedelta(hours=2))  # strategy still long -> must NOT re-enter
    assert not eng.broker.account(eng.symbols).positions


def test_agent_promotions_rate_limited(cfg, now):
    eng, imp, tk, _ = build(cfg, now)
    args = {"symbol": "BTC/USDT", "strategy": "ema_cross", "params": {"fast": 8, "slow": 55}, "why": "t"}
    first = tk.call("promote_strategy", args)
    second = tk.call("promote_strategy", {**args, "params": {"fast": 12, "slow": 89}})
    assert '"reason"' in first and "one promotion attempt" in second
    assert eng.journal.recent_events(kind="promote_attempt")


def test_lessons_budget(tmp_path):
    L = Lessons(tmp_path / "L.md", char_limit=60)
    assert L.add("BTC: mean reversion loses in trends").startswith("added")
    assert L.add("BTC: mean reversion loses in trends") == "already recorded"
    assert L.add("x" * 50).startswith("error")
    assert L.replace("mean reversion", "BTC: MR loses when ADX high") == "replaced"
    assert L.remove("ADX") == "removed"
    assert L.entries() == []


def test_playbooks(tmp_path):
    pb = Playbooks(tmp_path / "pb", [BUNDLED_PLAYBOOKS])
    names = {p["name"] for p in pb.index()}
    assert {"regime-check", "drawdown-response", "new-symbol-onboarding"} <= names
    assert pb.create("Bad Name", "d", "b").startswith("error")
    assert pb.create("vol-spike", "what to do on vol spikes", "1. reduce").startswith("created")
    assert "reduce" in pb.view("vol-spike")
    # patching a bundled playbook copies it into the writable root
    assert pb.patch("regime-check", "# Regime check", "# Regime check (v2)").startswith("patched")
    assert (tmp_path / "pb" / "regime-check" / "SKILL.md").read_text().count("(v2)") == 1
    assert "(v2)" not in (BUNDLED_PLAYBOOKS / "regime-check" / "SKILL.md").read_text()


# ---------------------------------------------------------------- LLM
def _setup_reviewer(cfg, now, reply):
    eng, imp, tk, clock = build(cfg, now)
    llm = FakeLLM([reply] * 50)
    eng.reviewer = make_reviewer(llm, tk)
    return eng, llm, clock


def _run_until_trade(eng, clock, now, n=200):
    for h in range(n):
        clock.set(now + timedelta(hours=h))
        eng.cycle(now + timedelta(hours=h))
        if eng.journal.rows("SELECT * FROM decisions WHERE llm_verdict != ''"):
            return


def test_reviewer_veto_blocks_entries(cfg, now):
    eng, llm, clock = _setup_reviewer(cfg, now, '{"verdict":"veto","size_mult":0,"note":"lesson #2"}')
    _run_until_trade(eng, clock, now)
    assert llm.calls, "reviewer never consulted"
    assert llm.calls[0]["json_mode"]
    vetoed = eng.journal.rows("SELECT * FROM decisions WHERE llm_verdict='veto'")
    assert vetoed and vetoed[0]["action"] == "vetoed"
    assert not eng.journal.recent_fills()


def test_reviewer_cannot_enlarge(cfg, now):
    eng, llm, clock = _setup_reviewer(cfg, now, '```json\n{"verdict":"reduce","size_mult":5}\n```')
    _run_until_trade(eng, clock, now)
    f = eng.journal.recent_fills()[0]
    d = eng.journal.rows("SELECT * FROM decisions WHERE llm_verdict!='' LIMIT 1")[0]
    assert f["qty"] * f["price"] <= 0.2 * 10_000 * 1.01  # clamped to 1.0x
    assert d["llm_verdict"] == "reduce"


def test_reviewer_errors_trade_at_half_size_by_default(cfg, now):
    eng2, llm2, clock2 = _setup_reviewer(cfg, now, RuntimeError("provider down"))
    _run_until_trade(eng2, clock2, now)
    assert eng2.journal.rows("SELECT * FROM decisions WHERE llm_verdict='error'")
    f = eng2.journal.recent_fills()[0]
    assert f["qty"] * f["price"] <= 0.5 * 0.2 * 10_000 * 1.01


def test_review_multiplier_verdict_first():
    assert review_multiplier("veto", None) == 0.0  # malformed size must not turn a veto into a trade
    assert review_multiplier("veto", 1.0) == 0.0
    assert review_multiplier("reduce", None) == 0.5
    assert review_multiplier("reduce", 5) == 0.5
    assert review_multiplier("reduce", 0.3) == 0.3
    assert review_multiplier("approve", 9) == 1.0
    with pytest.raises(ValueError):
        review_multiplier("yolo", 1)


def test_reviewer_veto_with_null_size_is_still_veto(cfg, now):
    eng, llm, clock = _setup_reviewer(cfg, now, '{"verdict":"veto","size_mult":null}')
    _run_until_trade(eng, clock, now)
    assert eng.journal.rows("SELECT * FROM decisions WHERE llm_verdict='veto'")
    assert not eng.journal.recent_fills()


def test_agent_tool_loop_and_gated_promotion(cfg, now):
    eng, imp, tk, _ = build(cfg, now)
    script = [
        [("memory", {"action": "add", "text": "BTC/USDT: trend-following works in synthetic regimes"}),
         ("market_snapshot", {"symbol": "BTC/USDT"})],
        [("promote_strategy", {"symbol": "BTC/USDT", "strategy": "sma_cross", "params": {"fast": 5, "slow": 200},
                               "why": "test"}),
         ("place_order", {"symbol": "BTC/USDT", "side": "buy", "notional": 100, "why": "no"}),
         ("bogus_tool", {})],
        "Summary: recorded one lesson.",
    ]
    llm = FakeLLM(script)
    agent = Agent(llm, tk)
    out = agent.run("review")
    assert out.startswith("Summary")
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert '"last"' in tool_msgs[1]["content"]
    assert "unknown tool place_order" in tool_msgs[3]["content"]  # not exposed without a human confirmer
    assert "unknown tool bogus_tool" in tool_msgs[4]["content"]
    assert "trend-following" in tk.lessons.render()
    # second system prompt build includes the lesson
    agent.run("again")
    assert "trend-following" in llm.calls[-1]["messages"][0]["content"]


def test_manual_order_requires_confirmation_and_caps(cfg, now):
    eng, imp, tk, _ = build(cfg, now)
    asked = []
    tk2 = Toolkit(eng, imp, tk.lessons, tk.playbooks, confirm=lambda p: asked.append(p) or False)
    assert "declined" in tk2.call("place_order", {"symbol": "BTC/USDT", "side": "buy", "notional": 100, "why": "t"})
    assert asked
    assert "max_position_pct" in tk2.call("place_order", {"symbol": "BTC/USDT", "side": "buy", "notional": 2500,
                                                          "why": "t"})
    assert "shorting" in tk2.call("place_order", {"symbol": "BTC/USDT", "side": "sell", "notional": 100, "why": "t"})
    tk3 = Toolkit(eng, imp, tk.lessons, tk.playbooks, confirm=lambda p: True)
    assert '"filled"' in tk3.call("place_order", {"symbol": "BTC/USDT", "side": "buy", "notional": 100, "why": "t"})


def test_reflect_records_event(cfg, now):
    eng, imp, tk, _ = build(cfg, now)
    agent = Agent(FakeLLM([[("journal_stats", {})], "Nothing new to learn."]), tk)
    assert reflect(agent) == "Nothing new to learn."
    assert eng.journal.recent_events(kind="reflect")
    assert "reflected_at_closed_trades" in eng.meta
