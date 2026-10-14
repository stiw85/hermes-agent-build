"""JEV per-bar checks: regime/fit/exit questions, shadow vs act, forward scoring, report."""

from __future__ import annotations

from datetime import timedelta

import pytest

from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import load_config
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine
from hermes_trader.jev import JevClient
from hermes_trader.jev_checks import JevChecker, build_check_state, check_questions, check_report
from hermes_trader.journal import Journal
from hermes_trader.models import Position, Signal

from .conftest import make_df


class Resp:
    def __init__(self, body):
        self.status_code = 200
        self._b = body
        self.text = ""

    def json(self):
        return self._b


class CheckSession:
    """Answers whatever was asked: regime + strategy_fits (+ exit_now)."""

    def __init__(self, fit=0.6, exit_p=0.2, fail=False):
        self.fit, self.exit_p, self.fail = fit, exit_p, fail
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        if self.fail:
            raise ConnectionError("down")
        a = {}
        for name in json["questions"]:
            if name == "regime":
                a[name] = {"type": "choice", "choice": "ranging", "confidence": 0.6}
            elif name == "strategy_fits":
                a[name] = {"type": "noul", "noul": self.fit}
            elif name == "exit_now":
                a[name] = {"type": "noul", "noul": self.exit_p}
            else:
                a[name] = {"type": "noul", "noul": 0.6}
        return Resp({"model": "fake", "answers": a, "usage": {"cost": 0.00002}})


CHECKS = {"enabled": True, "mode": "shadow", "regime_block_below": 0.35, "exit_above": 0.7, "horizon_bars": 3,
          "min_resolved": 10}
JEV = {"enabled": True, "mode": "shadow", "url": "u", "model": "m", "api_key_env": "X", "veto_below": 0.4,
       "reduce_below": 0.55, "checks": CHECKS}


def test_questions_and_state():
    q = check_questions("rsi_reversion", None)
    assert set(q) == {"regime", "strategy_fits"} and "mean reversion" in q["strategy_fits"]["instructions"]
    q2 = check_questions("sma_cross", "long")
    assert "exit_now" in q2 and "long position" in q2["exit_now"]["instructions"]
    df = make_df(300)
    sig = Signal("BTC/USDT", 1.0, "sma_cross", reason="r", atr=2.0)
    st = build_check_state(sig, Position("BTC/USDT", 1.0, 100.0, 110.0), df, "1h", ["L"])
    assert st["strategy"]["currently_wants"] == "long"
    assert st["open_position"] == {"side": "long", "unrealised_result_pct": 10.0, "unrealised_result_in_atr": 5.5}
    assert "open_position" not in build_check_state(sig, None, df, "1h", [])


class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def run(tmp_path, now, hours, checks=None, session=None, name="a"):
    cfg = load_config(overrides={"home": str(tmp_path / name), "jev": {**JEV, "checks": {**CHECKS, **(checks or {})}}})
    clock = Clock(now)
    eng = Engine(cfg, PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5))
    if session is not None:
        eng.jev_checks = JevChecker(JevClient("u", "m", "k", session=session), cfg["jev"], "1h")
    for h in range(hours):
        t = now + timedelta(hours=h)
        clock.set(t)
        eng.cycle(t)
    return eng


def fills_of(eng):
    return [(f["symbol"], f["side"], round(f["qty"], 9)) for f in reversed(eng.journal.recent_fills(1000))]


def test_shadow_changes_nothing(tmp_path, now):
    base = run(tmp_path, now, 150, name="base")
    s = CheckSession(fit=0.05, exit_p=0.99)  # would block and exit everything if it were acting
    shadow = run(tmp_path, now, 150, session=s, name="shadow")
    assert fills_of(base) and fills_of(base) == fills_of(shadow)
    rows = shadow.journal.jev_check_rows()
    assert {r["kind"] for r in rows} == {"regime", "exit"}
    assert all(r["applied"] == 0 for r in rows)
    assert len(s.calls) == 150 * 2  # one request per symbol per bar
    assert sum(1 for r in rows if r["resolved_ts"]) > 0  # older answers were scored


def test_act_exit_closes_and_blocks_reentry(tmp_path, now):
    eng = run(tmp_path, now, 150, checks={"mode": "act"}, session=CheckSession(fit=0.9, exit_p=0.95), name="x")
    exits = [r for r in eng.journal.jev_check_rows() if r["kind"] == "exit" and r["applied"]]
    assert exits, "expected JEV to close at least one position"
    assert eng.journal.recent_events(kind="jev")
    # after a JEV exit the strategy (still long) is held off until its own signal resets
    blocked = eng.journal.rows("SELECT * FROM decisions WHERE signal_reason LIKE 're-entry blocked%'")
    later = [d for d in blocked if "JEV exit" not in d["signal_reason"]]  # bars after the closing bar
    assert later and all(d["action"] == "hold" for d in later)
    closes = eng.journal.rows("SELECT * FROM decisions WHERE signal_reason LIKE '%JEV exit%'")
    assert closes and any(d["action"].startswith("sell") for d in closes)


def test_act_regime_block_stops_new_entries_only(tmp_path, now):
    eng = run(tmp_path, now, 150, checks={"mode": "act"}, session=CheckSession(fit=0.1, exit_p=0.0), name="r")
    assert not [f for f in eng.journal.recent_fills(1000) if f["side"] == "buy"]
    d = eng.journal.rows("SELECT * FROM decisions WHERE action LIKE 'vetoed by JEV regime%'")
    assert d and "standing aside" in d[0]["jev_note"]


def test_check_errors_never_stop_trading(tmp_path, now):
    base = run(tmp_path, now, 120, name="b2")
    broken = run(tmp_path, now, 120, checks={"mode": "act"}, session=CheckSession(fail=True), name="broken")
    assert fills_of(base) == fills_of(broken)
    assert all(r["error"] for r in broken.journal.jev_check_rows())


def test_forward_scoring(tmp_path):
    j = Journal(tmp_path / "j.sqlite")
    j.jev_check(ts="2026-01-01T00:00:00+00:00", symbol="X", kind="regime", p=0.2, side_sign=1, price=100.0)
    j.jev_check(ts="2026-01-01T00:00:00+00:00", symbol="X", kind="exit", p=0.9, side_sign=-1, price=100.0)
    j.jev_check(ts="2026-01-01T05:00:00+00:00", symbol="X", kind="regime", p=0.5, side_sign=1, price=100.0)
    n = j.jev_check_resolve("X", "2026-01-01T03:00:00+00:00", 110.0, "2026-01-01T06:00:00+00:00")
    assert n == 2
    rows = {(r["kind"], r["p"]): r for r in j.jev_check_rows()}
    assert rows[("regime", 0.2)]["fwd_ret"] == pytest.approx(0.10)
    assert rows[("exit", 0.9)]["fwd_ret"] == pytest.approx(-0.10)  # short position lost 10% by holding
    assert rows[("regime", 0.5)]["resolved_ts"] is None  # not old enough yet


def test_report_recommends_only_with_evidence():
    rows = []
    for _ in range(40):  # low fit -> strategy then loses, high fit -> wins
        rows.append({"kind": "regime", "p": 0.2, "side_sign": 1, "fwd_ret": -0.004, "resolved_ts": "t", "cost": 2e-5})
        rows.append({"kind": "regime", "p": 0.8, "side_sign": 1, "fwd_ret": 0.006, "resolved_ts": "t", "cost": 2e-5,
                     "regime": "trending_up"})
    for _ in range(30):
        rows.append({"kind": "exit", "p": 0.9, "side_sign": 1, "fwd_ret": -0.003, "resolved_ts": "t", "cost": 0})
    rep = check_report(rows, JEV)
    assert rep["regime"]["buckets"][0]["n"] == 40 and rep["regime"]["buckets"][0]["avg_fwd_pct"] == pytest.approx(-0.4)
    assert "Consider jev.checks.mode: act" in rep["regime"]["recommendation"]
    assert "Consider jev.checks.mode: act" in rep["exit"]["recommendation"]
    few = check_report(rows[:6], JEV)
    assert "Keep shadowing" in few["regime"]["recommendation"]
    flat = [dict(r, fwd_ret=0.001) for r in rows]
    assert "No edge yet" in check_report(flat, JEV)["regime"]["recommendation"]
