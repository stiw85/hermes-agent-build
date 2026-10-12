"""JEV decision model: client wire format, shadow vs gate, outcome tracking, report."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import load_config
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine
from hermes_trader.jev import JevClient, JevError, JevReviewer, build_state, questions, report
from hermes_trader.journal import Journal
from hermes_trader.models import Account, Order, Side, Signal
from hermes_trader.risk import RiskDecision

from .conftest import make_df


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body
        self.text = json.dumps(body)

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, p=0.7, fail_dict_state=False, status=200):
        self.calls = []
        self.p, self.fail_dict_state, self.status = p, fail_dict_state, status

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.status != 200:
            return Resp(self.status, {"error": "nope"})
        if self.fail_dict_state and not isinstance(json["state"], str):
            return Resp(400, {"error": "state must be a string"})
        return Resp(200, {"model": "jev-1.13.0", "answers": {
            "worth_taking": {"type": "noul", "noul": self.p},
            "regime": {"type": "choice", "choice": "trending_up", "confidence": 0.8,
                       "probabilities": {"trending_up": 0.8}}},
            "usage": {"input_tokens": 500, "output_tokens": 2, "cost": 0.00002}})


JC = {"enabled": True, "mode": "shadow", "url": "https://api.typesafe.ai/v1/systemone", "model": "jev-latest",
      "api_key_env": "TYPESAFE_API_KEY", "veto_below": 0.40, "reduce_below": 0.55, "on_error": "proceed",
      "min_shadow_trades": 3}


def test_client_wire_format_and_auth():
    s = FakeSession()
    c = JevClient(JC["url"], "jev-latest", "k3y", session=s)
    out = c.decide({"a": 1}, questions("buy"))
    req = s.calls[0]
    assert req["url"] == "https://api.typesafe.ai/v1/systemone"
    assert req["headers"]["Authorization"] == "Bearer k3y"
    assert req["json"]["model"] == "jev-latest" and req["json"]["state"] == {"a": 1}
    q = req["json"]["questions"]
    assert q["worth_taking"]["type"] == "noul" and set(q["worth_taking"]["criteria"]) == {"true", "false"}
    assert q["regime"]["type"] == "choice" and "ranging" in q["regime"]["criteria"]
    assert out["answers"]["worth_taking"]["noul"] == 0.7


def test_client_retries_with_text_state_and_reports_errors():
    s = FakeSession(fail_dict_state=True)
    c = JevClient(JC["url"], "jev-latest", "k", session=s)
    c.decide({"a": 1}, questions("buy"))
    assert isinstance(s.calls[-1]["json"]["state"], str)
    with pytest.raises(JevError, match="401"):
        JevClient(JC["url"], "m", "k", session=FakeSession(status=401)).decide({}, {})
    with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
        JevClient(JC["url"], "m", None)


def test_state_has_facts_not_arithmetic():
    df = make_df(300)
    sig = Signal("BTC/USDT", 1.0, "ema_cross", reason="ema_cross: target 0 -> 1", price=float(df.close.iloc[-1]), atr=1.0)
    dec = RiskDecision(Order("BTC/USDT", Side.BUY, 1.0), True, [], 2000.0, 0.0)
    st = build_state(sig, dec, Account(10_000, 10_000), df, "1h", {"live_closed_trades": 0}, ["lesson A"])
    assert st["market"]["trend_vs_sma50_sma200"] in ("up", "down", "mixed")
    assert st["proposed_trade"]["side"] == "buy" and "trend-following" in st["proposed_trade"]["strategy_style"]
    assert st["proposed_trade"]["size_pct_of_equity"] == 20.0
    assert st["lessons_from_past_trading"] == ["lesson A"]
    json.dumps(st)  # serialisable


def test_gate_thresholds():
    r = JevReviewer(JevClient("u", "m", "k", session=FakeSession()), {**JC, "mode": "gate"})
    assert r.verdict_for(0.2) == ("veto", 0.0)
    assert r.verdict_for(0.5) == ("reduce", 0.5)
    assert r.verdict_for(0.8) == ("approve", 1.0)
    with pytest.raises(ValueError):
        JevReviewer(r.client, {**JC, "veto_below": 0.6, "reduce_below": 0.5})
    with pytest.raises(ValueError):
        JevReviewer(r.client, {**JC, "mode": "yolo"})


# ---------------------------------------------------------------- engine integration
class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def make_engine(tmp_path, now, p, mode):
    cfg = load_config(overrides={"home": str(tmp_path / "home"), "jev": {**JC, "mode": mode}})
    clock = Clock(now)
    eng = Engine(cfg, PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5))
    eng.jev = JevReviewer(JevClient("u", "m", "k", session=FakeSession(p=p)), cfg["jev"], "1h", eng.journal, eng.book)
    return eng, clock


def run_until_entry(eng, clock, now, hours=200):
    for h in range(hours):
        t = now + timedelta(hours=h)
        clock.set(t)
        eng.cycle(t)
        if eng.journal.jev_rows():
            return t
    raise AssertionError("no entry was ever proposed")


def test_shadow_mode_changes_nothing_but_records(tmp_path, now):
    eng, clock = make_engine(tmp_path, now, p=0.1, mode="shadow")  # Jev hates it, but it's only watching
    run_until_entry(eng, clock, now)
    row = eng.journal.jev_rows()[0]
    assert row["p"] == 0.1 and row["verdict"] == "veto" and row["applied"] == 0 and row["taken"] == 1
    d = eng.journal.rows("SELECT * FROM decisions WHERE jev_p IS NOT NULL")[0]
    assert "(shadow)" in d["jev_note"] and d["action"].startswith("buy")
    assert eng.journal.recent_fills()


def test_gate_mode_vetoes_low_probability(tmp_path, now):
    eng, clock = make_engine(tmp_path, now, p=0.1, mode="gate")
    run_until_entry(eng, clock, now)
    row = eng.journal.jev_rows()[0]
    assert row["applied"] == 1 and row["taken"] == 0
    d = eng.journal.rows("SELECT * FROM decisions WHERE jev_p IS NOT NULL")[0]
    assert d["action"] == "vetoed by JEV"
    assert not eng.journal.recent_fills()


def test_gate_mode_halves_middling_probability(tmp_path, now):
    eng, clock = make_engine(tmp_path, now, p=0.5, mode="gate")
    run_until_entry(eng, clock, now)
    f = eng.journal.recent_fills()[0]
    assert f["qty"] * f["price"] <= 0.5 * 0.2 * 10_000 * 1.02


def test_jev_outage_never_blocks_by_default(tmp_path, now):
    eng, clock = make_engine(tmp_path, now, p=0.9, mode="gate")
    eng.jev.client.s = FakeSession(status=503)
    eng.jev.client.s.post = lambda *a, **k: (_ for _ in ()).throw(JevError("down"))
    run_until_entry(eng, clock, now)
    assert eng.journal.jev_rows()[0]["error"]
    assert eng.journal.recent_fills()  # on_error: proceed


def test_outcome_resolves_when_position_closes(tmp_path):
    j = Journal(tmp_path / "j.sqlite")
    sid = j.jev_score(symbol="X", side="buy", strategy="s", p=0.8, verdict="approve", mode="shadow", applied=0,
                      taken=0)
    j.jev_mark_taken(sid, "o1")
    j.jev_add_pnl("X", 12.5)  # partial close
    assert j.jev_rows()[0]["closed_ts"] is None
    j.jev_add_pnl("X", -2.5)
    j.jev_close("X")
    r = j.jev_rows()[0]
    assert r["outcome_pnl"] == pytest.approx(10.0) and r["closed_ts"]


def test_report_buckets_and_recommendation():
    rows = []
    for p, pnl in [(0.2, -10), (0.3, -5), (0.5, 2), (0.6, 4), (0.8, 8), (0.9, 6), (0.35, -7)]:
        rows.append({"p": p, "taken": 1, "closed_ts": "t", "outcome_pnl": pnl, "regime": "trending_up", "cost": 0.00002})
    rows.append({"p": 0.7, "taken": 1, "closed_ts": None, "outcome_pnl": None, "cost": 0.00002})  # still open
    rep = report(rows, JC)
    assert rep["resolved"] == 7 and rep["open"] == 1
    veto = rep["buckets"][0]
    assert veto["trades"] == 3 and veto["win_rate"] == 0.0 and veto["pnl"] == -22
    assert rep["what_if_gate_pnl"] == pytest.approx(22 - 0.5 * 2)
    assert rep["brier"] < rep["brier_base_rate"]
    assert "Consider jev.mode: gate" in rep["recommendation"]
    assert "Keep shadowing" in report(rows[:2], JC)["recommendation"]
    assert rep["cost_usd"] == pytest.approx(0.00016)


def test_old_journal_gets_new_columns(tmp_path):
    import sqlite3

    p = tmp_path / "old.sqlite"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, strategy TEXT, params TEXT, "
               "target REAL, price REAL, signal_reason TEXT, risk_notes TEXT, llm_verdict TEXT, llm_note TEXT, action TEXT)")
    db.commit()
    db.close()
    j = Journal(p)
    j.decision(symbol="X", action="hold", jev_p=0.5, jev_note="n")
    assert j.rows("SELECT jev_p FROM decisions")[0]["jev_p"] == 0.5
