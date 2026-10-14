"""Paper, ccxt (fake client) and Alpaca (fake HTTP) adapters + factory safety."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from hermes_trader.brokers import make_broker
from hermes_trader.brokers.alpaca_broker import AlpacaBroker
from hermes_trader.brokers.ccxt_broker import CCXTBroker
from hermes_trader.brokers.paper import PaperBroker
from hermes_trader.config import LIVE_ACK_ENV, LIVE_ACK_VALUE, load_config
from hermes_trader.data import CSVData, SyntheticData, save_csv
from hermes_trader.models import Order, Side

from .conftest import make_df


class FixedData:
    def __init__(self, px=100.0):
        self.px = px

    def fetch_ohlcv(self, s, tf, n):
        return make_df(n)

    def last_price(self, s):
        return self.px


def test_paper_accounting(tmp_path):
    data = FixedData(100)
    b = PaperBroker(data, tmp_path / "s.json", 1000, fee_bps=10, slippage_bps=0)
    f = b.submit(Order("X", Side.BUY, 5))
    assert f.status == "filled" and f.fee == pytest.approx(0.5)
    a = b.account()
    assert a.cash == pytest.approx(499.5) and a.positions["X"].qty == 5
    data.px = 120
    b.submit(Order("X", Side.BUY, 1))
    assert b.account().positions["X"].avg_price == pytest.approx((500 + 120) / 6)
    b.submit(Order("X", Side.SELL, 6))
    assert "X" not in b.account().positions
    # persisted
    b2 = PaperBroker(data, tmp_path / "s.json", 1000)
    assert b2.state["cash"] == pytest.approx(b.state["cash"])


def test_paper_rejects(tmp_path):
    b = PaperBroker(FixedData(100), None, 100, fee_bps=0, slippage_bps=0)
    assert b.submit(Order("X", Side.BUY, 5)).status == "rejected"  # 500 > 100 cash
    assert b.submit(Order("X", Side.SELL, 1)).status == "rejected"  # short disabled


def test_synthetic_is_deterministic_and_advances():
    t1 = datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    a = SyntheticData(t1).fetch_ohlcv("BTC/USDT", "1h", 50)
    b = SyntheticData(t2).fetch_ohlcv("BTC/USDT", "1h", 52)
    assert b.index[-1] - a.index[-1] == __import__("pandas").Timedelta(hours=2)
    common = a.index.intersection(b.index)
    assert len(common) == 50
    assert (a.loc[common, "close"] == b.loc[common, "close"]).all()
    assert SyntheticData(t1).fetch_ohlcv("ETH/USDT", "1h", 5)["close"].iloc[-1] != a["close"].iloc[-1]


def test_csv_roundtrip(tmp_path):
    df = make_df(30)
    save_csv(df, tmp_path, "BTC/USDT", "1h")
    back = CSVData(tmp_path).fetch_ohlcv("BTC/USDT", "1h", 10)
    assert len(back) == 10
    assert back["close"].iloc[-1] == pytest.approx(df["close"].iloc[-1])


# ---------------------------------------------------------------- ccxt
class FakeExchange:
    def __init__(self):
        self.orders = []
        self.now = 1_700_000_000_000

    def load_markets(self):
        return {"BTC/USDT": {"limits": {"amount": {"min": 0.0001}, "cost": {"min": 5}}}}

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, symbol, tf, since=None, limit=None):
        start = since if since is not None else self.now - limit * 3_600_000
        rows = []
        t = start
        while t <= self.now and len(rows) < limit:
            rows.append([t, 1, 2, 0.5, 1.5, 10])
            t += 3_600_000
        return rows

    def fetch_ticker(self, s):
        return {"last": 50_000.0}

    def amount_to_precision(self, s, a):
        return f"{a:.4f}"

    def create_order(self, symbol, type_, side, amount, price, params):
        self.orders.append((symbol, type_, side, amount, params))
        return {"id": "o1", "filled": amount, "average": 50_010.0, "fee": {"cost": 1.2}}

    def fetch_balance(self):
        return {"total": {"USDT": 1000.0, "BTC": 0.02}, "free": {"USDT": 900.0}}


def test_ccxt_broker(tmp_path):
    x = FakeExchange()
    b = CCXTBroker(client=x, state_path=tmp_path / "basis.json")
    assert b.submit(Order("BTC/USDT", Side.BUY, 0.00001)).status == "rejected"  # below min amount
    f = b.submit(Order("BTC/USDT", Side.BUY, 0.01))
    assert f.status == "filled" and f.price == 50_010.0 and f.fee == 1.2
    assert x.orders[-1][1:4] == ("market", "buy", 0.01)
    a = b.account(["BTC/USDT"])
    assert a.cash == 900 and a.positions["BTC/USDT"].avg_price == 50_010.0
    # 0.01 BTC held before the bot is ignored: only the bot's own 0.01 counts
    assert a.positions["BTC/USDT"].qty == pytest.approx(0.01)
    assert a.equity == pytest.approx(1000 + 0.01 * 50_000)
    assert json.loads((tmp_path / "basis.json").read_text())["BTC/USDT"]["qty"] == pytest.approx(0.01)
    df = b.fetch_ohlcv("BTC/USDT", "1h", 2500)  # paginates past 1000
    assert len(df) == 2500 and df.index.is_monotonic_increasing


def test_ccxt_rejects_mixed_quotes(tmp_path):
    b = CCXTBroker(client=FakeExchange(), state_path=tmp_path / "b.json")
    with pytest.raises(ValueError, match="one quote currency"):
        b.account(["BTC/USDT", "ETH/BTC"])


class SlowExchange(FakeExchange):
    """Acks market orders as open with nothing filled; fills on the 2nd poll (or never)."""

    def __init__(self, fills=True):
        super().__init__()
        self.fills, self.polls, self.cancelled = fills, 0, []
        self.open = [{"id": "x1", "clientOrderId": "ht-abc"}, {"id": "u1", "clientOrderId": "mine"}]

    def create_order(self, symbol, type_, side, amount, price, params):
        self.amount = amount
        return {"id": "o2", "status": "open", "filled": None, "average": None}

    def fetch_order(self, oid, symbol):
        self.polls += 1
        if self.fills and self.polls >= 2:
            return {"id": oid, "status": "closed", "filled": self.amount, "cost": self.amount * 50_000,
                    "fees": [{"cost": 0.0001, "currency": "BTC"}]}
        return {"id": oid, "status": "open", "filled": 0}

    def cancel_order(self, oid, symbol):
        self.cancelled.append(oid)

    def fetch_open_orders(self, symbol):
        return self.open


def test_ccxt_polls_until_filled_and_nets_base_fee(tmp_path):
    x = SlowExchange(fills=True)
    b = CCXTBroker(client=x, state_path=tmp_path / "b.json")
    b._sleep = lambda s: None
    f = b.submit(Order("BTC/USDT", Side.BUY, 0.01))
    assert f.status == "filled" and f.price == pytest.approx(50_000) and f.fee == pytest.approx(5.0)
    assert b.basis["BTC/USDT"]["qty"] == pytest.approx(0.0099)  # fee taken in BTC
    assert b.basis["BTC/USDT"]["avg_price"] == pytest.approx(50_000)


def test_ccxt_cancels_unfilled_market_order(tmp_path):
    x = SlowExchange(fills=False)
    b = CCXTBroker(client=x, state_path=tmp_path / "b.json")
    b._sleep = lambda s: None
    f = b.submit(Order("BTC/USDT", Side.BUY, 0.01))
    assert f.status == "rejected" and f.qty == 0 and "o2" in x.cancelled
    assert "BTC/USDT" not in b.basis
    assert b.cancel_open("BTC/USDT") == 1 and x.cancelled[-1] == "x1"  # never touches the user's own order


# ---------------------------------------------------------------- alpaca
class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body
        self.content = b"x" if body is not None else b""
        self.text = json.dumps(body)

    def json(self):
        return self._b


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.order_polls = 0

    def request(self, method, url, timeout=None, params=None, json=None):
        self.calls.append((method, url, params, json))
        if url.endswith("/v2/account"):
            return Resp(200, {"cash": "5000", "equity": "7000", "currency": "USD"})
        if url.endswith("/v2/positions"):
            return Resp(200, [{"symbol": "BTCUSD", "qty": "0.01", "avg_entry_price": "60000", "current_price": "61000"},
                              {"symbol": "SPY", "qty": "2", "avg_entry_price": "500", "current_price": "505"}])
        if url.endswith("/v2/orders") and method == "POST":
            return Resp(200, {"id": "a1", "status": "new"})
        if "/v2/orders/a1" in url:
            self.order_polls += 1
            return Resp(200, {"id": "a1", "status": "filled", "filled_qty": "2", "filled_avg_price": "501.5"})
        if url.endswith("/v2/clock"):
            return Resp(200, {"is_open": False})
        if "/v2/stocks/SPY/bars" in url:
            if params.get("page_token"):
                return Resp(200, {"bars": [{"t": "2026-01-02T15:00:00Z", "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 9}],
                                  "next_page_token": None})
            return Resp(200, {"bars": [{"t": "2026-01-02T14:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}],
                              "next_page_token": "p2"})
        if "/crypto/us/bars" in url:
            return Resp(200, {"bars": {"BTC/USD": [{"t": "2026-01-02T14:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5,
                                                    "v": 9}]}, "next_page_token": None})
        if "/crypto/us/latest/trades" in url:
            return Resp(200, {"trades": {"BTC/USD": {"p": 61000.5}}})
        return Resp(404, {"message": "not found"})


def test_alpaca_broker(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = FakeSession()
    b = AlpacaBroker(key_id="k", secret="s", session=s)
    a = b.account(["BTC/USD", "SPY"])
    assert a.equity == 7000 and set(a.positions) == {"BTC/USD", "SPY"}
    assert a.positions["SPY"].avg_price == 500
    df = b.fetch_ohlcv("SPY", "1h", 10)
    assert list(df["close"]) == [1.5, 2.5]  # paginated
    assert b.fetch_ohlcv("BTC/USD", "1h", 10)["close"].iloc[-1] == 1.5
    assert b.last_price("BTC/USD") == 61000.5
    assert b.is_tradable("SPY") is False and b.is_tradable("BTC/USD") is True
    f = b.submit(Order("SPY", Side.BUY, 2))
    assert f.status == "filled" and f.price == 501.5 and f.qty == 2
    post = [c for c in s.calls if c[0] == "POST"][0][3]
    assert post["time_in_force"] == "day" and post["qty"] == "2"
    assert s.headers["APCA-API-KEY-ID"] == "k"
    assert b.base.startswith("https://paper-api")


# ---------------------------------------------------------------- factory safety
def test_live_requires_latch(tmp_path, monkeypatch):
    monkeypatch.delenv(LIVE_ACK_ENV, raising=False)
    cfg = load_config(overrides={"home": str(tmp_path), "mode": "live",
                                 "broker": {"name": "ccxt", "sandbox": False}})
    with pytest.raises(RuntimeError, match=LIVE_ACK_ENV):
        make_broker(cfg)
    monkeypatch.setenv(LIVE_ACK_ENV, LIVE_ACK_VALUE)
    cfg2 = load_config(overrides={"home": str(tmp_path), "mode": "live", "broker": {"name": "paper"}})
    with pytest.raises(RuntimeError, match="real broker"):
        make_broker(cfg2)


def test_alpaca_live_needs_paper_false(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_ACK_ENV, LIVE_ACK_VALUE)
    cfg = load_config(overrides={"home": str(tmp_path), "mode": "live", "broker": {"name": "alpaca"}})
    with pytest.raises(RuntimeError, match="paper: false"):
        make_broker(cfg)


def test_paper_mode_refuses_real_exchange(tmp_path):
    cfg = load_config(overrides={"home": str(tmp_path), "broker": {"name": "ccxt", "sandbox": False}})
    with pytest.raises(RuntimeError, match="real orders"):
        make_broker(cfg)


def test_default_is_paper(tmp_path):
    cfg = load_config(overrides={"home": str(tmp_path)})
    assert not cfg.is_live
    assert make_broker(cfg).name == "paper"
