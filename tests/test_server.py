"""Local API used by the desktop app."""

from __future__ import annotations

import http.client
import json
import threading
import time

import pytest

from hermes_trader.agent import Agent
from hermes_trader.config import load_config
from hermes_trader.runtime import build
from hermes_trader.server import Service, make_server, write_token

from .conftest import FakeLLM


@pytest.fixture
def api(tmp_path):
    cfg = load_config(overrides={"home": str(tmp_path / "home")})
    app = build(cfg)
    httpd, svc, token = make_server(app, port=0, token="t0k")
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    def call(method, path, body=None, token="t0k", host=None, ctype="application/json", extra=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        headers = {"Host": host or f"127.0.0.1:{port}", **(extra or {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = ctype
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"null"))
        c.close()
        return out

    yield call, svc, app
    if svc.bot.get("running"):
        svc.stop_bot()
    httpd.shutdown()
    httpd.server_close()


def test_auth_and_host_guard(api):
    call, *_ = api
    assert call("GET", "/api/health", token=None)[0] == 200
    assert call("GET", "/api/status", token=None)[0] == 401
    assert call("GET", "/api/status", token="wrong")[0] == 401
    assert call("GET", "/api/status", host="evil.example:80")[0] == 403
    assert call("POST", "/api/halt", {"reason": "x"}, ctype="text/plain")[0] == 415
    assert call("GET", "/api/nope")[0] == 404


def test_read_endpoints(api):
    call, svc, app = api
    for path in ["/api/status", "/api/equity", "/api/fills", "/api/decisions", "/api/events", "/api/stats",
                 "/api/book", "/api/strategies", "/api/lessons", "/api/playbooks", "/api/config", "/api/jev",
                 "/api/playbook?name=regime-check"]:
        status, body = call("GET", path)
        assert status == 200 and body["ok"], (path, body)
    st = call("GET", "/api/status")[1]["data"]
    assert st["mode"] == "paper" and st["bot"]["running"] is False and st["symbols"] == ["BTC/USDT", "ETH/USDT"]
    cfg = call("GET", "/api/config")[1]["data"]
    assert "api_key_env" not in cfg["llm"] and cfg["risk"]["max_drawdown_pct"] == 0.15
    c = call("GET", "/api/candles?symbol=BTC/USDT&bars=120")[1]["data"]
    assert len(c["candles"]) == 120 and len(c["candles"][0]) == 6 and c["snapshot"]["last"] > 0
    assert call("GET", "/api/candles?symbol=DOGE/USDT")[0] == 400


def test_actions(api):
    call, svc, app = api
    rep = call("POST", "/api/cycle", {})[1]["data"]
    assert set(rep["symbols"]) == {"BTC/USDT", "ETH/USDT"}
    assert call("GET", "/api/equity")[1]["data"]
    bt = call("POST", "/api/backtest", {"symbol": "BTC/USDT", "strategy": "ema_cross",
                                        "params": {"fast": 12, "slow": 55}, "bars": 800})[1]["data"]
    assert bt["result"]["strategy"] == "ema_cross" and len(bt["curve"]) > 100 and len(bt["curve"][0]) == 3
    opt = call("POST", "/api/optimize", {"symbol": "ETH/USDT", "promote": False})[1]["data"]
    assert "leaderboard" in opt and opt["promoted"] is False
    assert call("POST", "/api/halt", {"reason": "test"})[1]["data"] == "halted"
    assert call("GET", "/api/status")[1]["data"]["risk"]["halted"] is True
    assert call("POST", "/api/resume", {})[1]["data"] == "resumed"
    assert call("POST", "/api/flatten", {})[0] == 400  # needs typed confirmation
    assert call("POST", "/api/flatten", {"confirm": "FLATTEN"})[0] == 200
    assert not app.engine.broker.account(app.engine.symbols).positions
    assert call("POST", "/api/rollback", {"symbol": "BTC/USDT"})[1]["data"] == "nothing to roll back"
    assert call("POST", "/api/chat", {"message": "hi"})[0] == 409  # LLM disabled


def test_bot_thread_start_stop(api, monkeypatch):
    call, svc, app = api
    monkeypatch.setattr(app, "next_wake", lambda now=None: time.time() + 3600)
    assert call("POST", "/api/bot/start", {})[1]["data"]["running"] is True
    for _ in range(100):
        if svc.bot.get("last_tick"):
            break
        time.sleep(0.1)
    st = call("GET", "/api/status")[1]["data"]["bot"]
    assert st["running"] and st["last_tick"] and st["next_cycle"]
    assert call("POST", "/api/bot/stop", {})[1]["data"]["running"] is False
    kinds = [e["message"] for e in app.engine.journal.recent_events(kind="bot")]
    assert any("started" in k for k in kinds) and any("stopped" in k for k in kinds)


def test_chat_uses_agent_without_order_tool(api):
    call, svc, app = api
    llm = FakeLLM([[("journal_stats", {})], "All quiet."])
    svc.chat_agent = Agent(llm, app.toolkit)
    out = call("POST", "/api/chat", {"message": "how are we doing?"})[1]["data"]
    assert out["reply"] == "All quiet." and out["tools"][0]["name"] == "journal_stats"
    names = {t["function"]["name"] for t in llm.calls[0]["tools"]}
    assert "place_order" not in names and "memory" in names


def test_token_file_is_private(tmp_path):
    p = write_token(tmp_path, "abc")
    assert p.read_text() == "abc" and (p.stat().st_mode & 0o777) == 0o600


def test_service_shares_lock_with_toolkit(tmp_path):
    app = build(load_config(overrides={"home": str(tmp_path)}))
    svc = Service(app)
    assert app.toolkit.lock is svc.lock


def test_backend_exits_when_app_goes_away(tmp_path):
    """The desktop app holds the backend's stdin open; EOF (quit, crash, kill -9) must stop trading and exit."""
    import os
    import subprocess
    import sys

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"home: {tmp_path / 'home'}\n")
    p = subprocess.Popen([sys.executable, "-m", "hermes_trader", "-c", str(cfg), "serve", "--port", "0", "--run"],
                         env={**os.environ, "HERMES_TRADER_EXIT_ON_STDIN_EOF": "1"}, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=os.getcwd())
    try:
        assert "hermes_trader_api" in p.stdout.readline()
        p.stdin.close()  # what the OS does when the app dies
        assert p.wait(timeout=60) is not None
        from hermes_trader.journal import Journal

        msgs = [e["message"] for e in Journal(tmp_path / "home" / "journal.sqlite").recent_events(kind="bot")]
        assert any("desktop app went away" in m for m in msgs), msgs
    finally:
        if p.poll() is None:
            p.kill()


def test_sigterm_is_graceful(tmp_path):
    import os
    import signal
    import subprocess
    import sys

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"home: {tmp_path / 'home'}\n")
    p = subprocess.Popen([sys.executable, "-m", "hermes_trader", "-c", str(cfg), "serve", "--port", "0", "--run"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=os.getcwd())
    try:
        assert "hermes_trader_api" in p.stdout.readline()
        time.sleep(1.0)
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=60) == 0
    finally:
        if p.poll() is None:
            p.kill()


def test_double_start_makes_one_thread(api, monkeypatch):
    call, svc, app = api
    monkeypatch.setattr(app, "next_wake", lambda now=None: time.time() + 3600)
    results = []
    ts = [threading.Thread(target=lambda: results.append(call("POST", "/api/bot/start", {}))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    bots = [t for t in threading.enumerate() if t.name == "hermes-trader-bot"]
    assert len(bots) == 1
    svc.stop_bot()


def test_status_does_not_block_on_a_running_cycle(api):
    call, svc, app = api
    assert call("GET", "/api/status")[0] == 200  # warm the snapshot
    svc._status_cache = (0.0, svc._status_cache[1])  # expire it
    hold = threading.Event()
    release = threading.Event()

    def busy_cycle():
        with svc.lock:
            hold.set()
            release.wait(10)

    t = threading.Thread(target=busy_cycle)
    t.start()
    hold.wait()
    t0 = time.time()
    status, body = call("GET", "/api/status")
    assert status == 200 and body["data"]["busy"] is True and time.time() - t0 < 3
    assert call("GET", "/api/fills")[0] == 200  # journal reads don't need the engine lock
    release.set()
    t.join()


def test_stop_reports_stopping_until_cycle_finishes(api, monkeypatch):
    call, svc, app = api
    monkeypatch.setattr(app, "next_wake", lambda now=None: time.time() + 3600)
    started = threading.Event()
    release = threading.Event()

    def slow_tick():
        started.set()
        release.wait(10)
        return {}

    monkeypatch.setattr(app, "tick", slow_tick)
    call("POST", "/api/bot/start", {})
    started.wait(5)
    st = svc.stop_bot(wait=0.2)
    assert st["stopping"] is True and st["running"] is False
    assert call("POST", "/api/bot/start", {})[0] == 409  # can't restart until the cycle is done
    release.set()
    for _ in range(50):
        if not svc.bot_state()["stopping"]:
            break
        time.sleep(0.1)
    assert call("POST", "/api/bot/start", {})[1]["data"]["running"] is True
    svc.stop_bot()


def test_health_proves_token_without_revealing_it(api):
    import hashlib
    import hmac

    call, *_ = api
    assert "proof" not in call("GET", "/api/health", token=None)[1]
    status, body = call("GET", "/api/health", token=None, extra={"X-Challenge": "abcdef0123456789"})
    assert status == 200
    assert body["proof"] == hmac.new(b"t0k", b"abcdef0123456789", hashlib.sha256).hexdigest()
    assert "t0k" not in json.dumps(body)


def test_token_file_rewritten_private_even_if_it_existed(tmp_path):
    p = tmp_path / "api_token"
    p.write_text("old")
    p.chmod(0o644)
    write_token(tmp_path, "new")
    assert p.read_text() == "new" and (p.stat().st_mode & 0o777) == 0o600


def test_agent_cannot_call_tools_it_was_not_offered(tmp_path):
    from hermes_trader.agent import Agent

    app = build(load_config(overrides={"home": str(tmp_path)}))
    llm = FakeLLM([[("rollback_strategy", {"symbol": "BTC/USDT"})], "ok"])
    agent = Agent(llm, app.toolkit)
    agent.run("hi", tools=["journal_stats"])
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert "not available here" in tool_msgs[0]["content"]
