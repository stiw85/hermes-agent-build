"""Volatility regime (realised + implied), implied-vol feeds, macro-event blackout."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import DEFAULTS, load_config
from hermes_trader.data import SyntheticData
from hermes_trader.engine import Engine
from hermes_trader.filters import EntryFilters, parse_events
from hermes_trader.vol import ImpliedVol

from .conftest import make_df

UTC = timezone.utc


def mk(**over):
    return EntryFilters({**DEFAULTS["filters"], **over}, DEFAULTS["risk"])


def test_parse_events_timezones():
    ev = parse_events(["2026-10-28 14:00 America/New_York FOMC", "2026-12-09 14:00 America/New_York FOMC",
                       "2026-11-10T13:30Z CPI (Oct)", "2026-11-11 09:00 UTC thing"])
    assert ev[0] == (datetime(2026, 10, 28, 18, 0, tzinfo=UTC), "FOMC")  # EDT: UTC-4
    assert ev[1] == (datetime(2026, 11, 10, 13, 30, tzinfo=UTC), "CPI (Oct)")
    assert ev[3] == (datetime(2026, 12, 9, 19, 0, tzinfo=UTC), "FOMC")  # EST after Nov 1: UTC-5
    with pytest.raises(ValueError, match="bad event"):
        parse_events(["next tuesday-ish"])
    assert len(EntryFilters(DEFAULTS["filters"], DEFAULTS["risk"]).events) >= 10  # built-in list parses


def test_event_blackout_window():
    f = mk(events={"enabled": True, "before_minutes": 60, "after_minutes": 30, "action": "skip",
                   "dates": ["2026-10-28 14:00 America/New_York FOMC"]})
    at = datetime(2026, 10, 28, 18, 0, tzinfo=UTC)
    r = f.check_events(at - timedelta(minutes=45))
    assert not r.passed and r.mult == 0 and "FOMC in 45 min" in r.note
    assert not f.check_events(at + timedelta(minutes=20)).passed
    assert f.check_events(at + timedelta(minutes=31)).passed
    early = f.check_events(at - timedelta(hours=5))
    assert early.passed and "next event: FOMC 2026-10-28 18:00Z" in early.note
    red = mk(events={"enabled": True, "action": "reduce", "dates": ["2026-10-28 18:00 UTC FOMC"]})
    assert red.check_events(at).mult == 0.5


def test_vol_regime_realised_and_implied():
    f = mk(vol={"enabled": True, "short_bars": 24, "long_bars": 720, "max_expansion": 2.0,
                "max_iv_premium": 1.5, "reduce_to": 0.5})
    calm = make_df(900, seed=4, trend=0.0, vol=0.005)
    ok = f.check_vol(calm, "BTC/USDT")
    assert ok.passed and ok.value == pytest.approx(1.0, abs=0.5)
    wild = calm.copy()
    rng = np.random.default_rng(1)
    c = wild["close"].to_numpy().copy()
    c[-24:] = c[-25] * np.exp(np.cumsum(rng.normal(0, 0.03, 24)))  # 6x normal volatility
    wild["close"] = c
    bad = f.check_vol(wild, "BTC/USDT")
    assert not bad.passed and bad.mult == 0.5 and "trade smaller" in bad.note
    # options pricing a much bigger move than recent reality
    rv = float(np.log(calm["close"]).diff().std() * np.sqrt(365 * 24)) * 100
    iv_hot = f.check_vol(calm, "BTC/USDT", (rv * 2.0, "Deribit DVOL BTC"))
    assert not iv_hot.passed and "Deribit DVOL BTC" in iv_hot.note
    assert f.check_vol(calm, "BTC/USDT", (rv * 1.1, "Deribit DVOL BTC")).passed


class Resp:
    def __init__(self, js=None, text="", status=200):
        self._js, self.text, self.status_code = js, text, status

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Sess:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_implied_vol_feeds_and_cache():
    s = Sess([Resp({"result": {"data": [[1, 50, 51, 49, 52.5], [2, 52, 55, 51, 54.0]], "continuation": None}}),
              Resp(text="DATE,OPEN,HIGH,LOW,CLOSE\n10/09/2026,15,16,14,15.5\n10/12/2026,16,19,15,18.25\n")])
    iv = ImpliedVol(session=s)
    assert iv.for_symbol("BTC/USDT") == (54.0, "Deribit DVOL BTC")
    assert iv.for_symbol("BTC/USDT") == (54.0, "Deribit DVOL BTC")  # cached: no second request
    assert s.calls[0][1]["currency"] == "BTC" and s.calls[0][1]["resolution"] == "3600"
    assert iv.for_symbol("AAPL") == (18.25, "CBOE VIX")
    assert iv.for_symbol("SOL/USDT") is None  # no DVOL for it
    assert len(s.calls) == 2
    frac = ImpliedVol(session=Sess([Resp({"result": {"data": [[1, 0.5, 0.5, 0.5, 0.55]]}})]))
    assert frac.for_symbol("ETH/USDT")[0] == pytest.approx(55.0)
    down = ImpliedVol(session=Sess([ConnectionError("blocked")]))
    assert down.for_symbol("ETH/USDT") is None  # failures are just "no data"


class Clock(SyntheticData):
    def set(self, t):
        self._now = t


def _run(tmp_path, now, filters, name):
    cfg = load_config(overrides={"home": str(tmp_path / name), "filters": filters})
    clock = Clock(now)
    broker = PaperBroker(clock, cfg.home / "paper.json", 10_000, 10, 5)
    eng = Engine(cfg, broker)
    if filters.get("enabled", True):
        eng.filters = EntryFilters(cfg["filters"], cfg["risk"], broker, cfg["timeframe"])
    for h in range(120):
        t = now + timedelta(hours=h)
        clock.set(t)
        eng.cycle(t)
    return eng


def test_act_mode_reduces_size_instead_of_skipping(tmp_path, now):
    off = {k: {"enabled": False} for k in ("levels", "stretch", "flow", "events")}
    base = _run(tmp_path, now, {"enabled": False}, "base")
    half = _run(tmp_path, now, {"mode": "act", **off, "vol": {"max_expansion": 0.0, "iv": False, "reduce_to": 0.5}},
                "half")
    b = next(f for f in reversed(base.journal.recent_fills(1000)) if f["side"] == "buy")
    h = next(f for f in reversed(half.journal.recent_fills(1000)) if f["side"] == "buy")
    assert b["symbol"] == h["symbol"] and h["qty"] == pytest.approx(b["qty"] * 0.5, rel=0.02)
    notes = half.journal.rows("SELECT risk_notes FROM decisions WHERE risk_notes LIKE '%vol:%size x0.5%'")
    assert notes
