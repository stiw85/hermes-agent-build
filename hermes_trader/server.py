"""Local HTTP API for the desktop app (`hermes-trader serve`).

Security model:
- binds to 127.0.0.1 only; requests with any other Host header are refused (DNS-rebinding guard)
- every /api route except /api/health needs `Authorization: Bearer <token>`; the token is random per
  start, written to <home>/api_token (0600) or taken from HERMES_TRADER_API_TOKEN
- no CORS headers: browsers on other origins can't read responses or send the auth header
- the GUI gets the same powers as the CLI minus anything the CLI doesn't have: risk limits are
  read-only and there is no manual-order endpoint
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import __version__
from .agent import Agent
from .backtest import backtest, buy_and_hold
from .brokers.base import asset_class_of
from .runtime import App
from .strategies import describe, make

log = logging.getLogger("hermes_trader.server")

TOKEN_ENV = "HERMES_TRADER_API_TOKEN"
EXIT_ON_EOF_ENV = "HERMES_TRADER_EXIT_ON_STDIN_EOF"  # set by the desktop app: exit when it goes away
CHAT_TOOLS = ["get_portfolio", "jev_report", "market_snapshot", "list_strategies", "strategy_book", "run_backtest", "optimize",
              "promote_strategy", "rollback_strategy", "journal_stats", "recent_trades", "recent_decisions",
              "memory", "playbook"]


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def clean(obj: Any) -> Any:
    """JSON-safe: NaN/inf -> None, datetimes -> ISO strings."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "item") and callable(obj.item):  # numpy scalars
        return clean(obj.item())
    return obj


def downsample(rows: list, limit: int) -> list:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    out = [rows[int(i * step)] for i in range(limit)]
    out[-1] = rows[-1]
    return out


class Service:
    """Owns the App, a lock around everything that touches the engine/broker, and the bot thread."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.lock = threading.RLock()
        app.toolkit.lock = self.lock
        self._stop = threading.Event()
        self._ctl = threading.Lock()  # serialises start/stop so two clicks can't make two bot threads
        self._thread: threading.Thread | None = None
        self.bot: dict[str, Any] = {"running": False, "stopping": False, "next_cycle": None, "last_tick": None,
                                    "last_error": None, "started_at": None}
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        self.chat_agent = None
        if app.agent:
            self.chat_agent = Agent(app.agent.llm, app.toolkit, app.agent.max_iter)

    # ---- bot thread ------------------------------------------------------
    def bot_state(self) -> dict[str, Any]:
        alive = bool(self._thread and self._thread.is_alive())
        stopping = alive and self._stop.is_set()
        return dict(self.bot, running=alive and not stopping, stopping=stopping)

    def start_bot(self) -> dict[str, Any]:
        with self._ctl:
            if self._thread and self._thread.is_alive():
                if self._stop.is_set():
                    raise ApiError(409, "The bot is still finishing its last cycle. Try again in a moment.")
                return self.bot_state()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="hermes-trader-bot", daemon=True)
            self.bot.update(started_at=datetime.now(timezone.utc).isoformat(), last_error=None, next_cycle=None)
            self._thread.start()
            self.app.engine.journal.event("bot", "bot started from desktop app")
        self._status_cache = None
        return self.bot_state()

    def stop_bot(self, wait: float = 2.0) -> dict[str, Any]:
        """Ask the loop to stop. A cycle in progress always finishes; until then state is 'stopping'."""
        with self._ctl:
            was = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=wait)
            self.bot["next_cycle"] = None
            if was:
                self.app.engine.journal.event("bot", "bot stopped from desktop app")
        self._status_cache = None
        return self.bot_state()

    def shutdown(self, wait: float = 120.0) -> None:
        """Graceful exit: stop the loop and wait for any in-flight cycle so no order goes unjournaled."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=wait)
        if self.lock.acquire(timeout=wait):  # also waits out a manual cycle/flatten running in a handler
            self.lock.release()

    def _loop(self) -> None:
        with self.lock:
            self.app.notify(f"Hermes Trader started: {self.app.cfg['mode']} via {self.app.engine.broker.name}")
        while not self._stop.is_set():
            try:
                with self.lock:
                    self.app.tick()
                self.bot["last_tick"] = datetime.now(timezone.utc).isoformat()
                self.bot["last_error"] = None
                self._status_cache = None
                wake = self.app.next_wake()
            except Exception as e:  # keep the thread alive; surface the error in the GUI
                log.exception("bot tick failed")
                self.bot["last_error"] = f"{type(e).__name__}: {e}"
                wake = time.time() + 60
            if not self._stop.is_set():
                self.bot["next_cycle"] = datetime.fromtimestamp(wake, timezone.utc).isoformat()
            self._stop.wait(max(1.0, wake - time.time()))
        self.bot["next_cycle"] = None

    # ---- reads ---------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        cached = self._status_cache
        if cached and time.time() - cached[0] < 4:
            return dict(cached[1], bot=self.bot_state())
        cfg = self.app.cfg
        # A trading cycle holds the lock for its whole duration (network calls, optional LLM review).
        # Don't make the GUI wait for it: serve the last snapshot, flagged busy.
        if not self.lock.acquire(timeout=0.5 if cached else 3):
            if cached:
                return dict(cached[1], bot=self.bot_state(), busy=True)
            return self._lite_status()
        try:
            st = self.app.engine.status()
            stats = self.app.engine.journal.stats()
        finally:
            self.lock.release()
        eq = st["equity"]
        sod = st["risk"].get("start_of_day_equity") or eq
        peak = st["risk"].get("peak_equity") or eq
        out = {
            **st,
            "version": __version__,
            "symbols": list(cfg["symbols"]),
            "timeframe": cfg["timeframe"],
            "llm_enabled": bool(self.app.agent),
            "jev_mode": cfg["jev"]["mode"] if cfg["jev"].get("enabled") else "off",
            "allow_short": cfg["allow_short"],
            "day_pnl": round(eq - sod, 2),
            "day_pnl_pct": round(eq / sod - 1, 5) if sod else 0.0,
            "drawdown_pct": round(1 - eq / peak, 5) if peak else 0.0,
            "realized_pnl": stats["realized_pnl"],
            "closed_trades": stats["closed_trades"],
            "bot": self.bot_state(),
            "busy": False,
        }
        out = clean(out)
        self._status_cache = (time.time(), out)
        return out

    def _lite_status(self) -> dict[str, Any]:
        """Status without touching the broker (used before the first snapshot while a cycle runs)."""
        cfg, e = self.app.cfg, self.app.engine
        return clean({
            "mode": cfg["mode"], "broker": e.broker.name, "equity": None, "cash": None, "currency": "",
            "positions": {}, "risk": e.state.to_dict(), "strategies": {s: e.book.entry(s).get("strategy") for s in e.symbols},
            "last_cycle": e.meta.get("last_cycle"), "version": __version__, "symbols": list(cfg["symbols"]),
            "timeframe": cfg["timeframe"], "llm_enabled": bool(self.app.agent), "allow_short": cfg["allow_short"],
            "jev_mode": cfg["jev"]["mode"] if cfg["jev"].get("enabled") else "off",
            "day_pnl": None, "day_pnl_pct": None, "drawdown_pct": None, "realized_pnl": None, "closed_trades": None,
            "bot": self.bot_state(), "busy": True,
        })

    def jev(self, q: dict[str, str]) -> dict[str, Any]:
        from .jev import report

        jc = self.app.cfg["jev"]
        rows = self.app.engine.journal.jev_rows()
        recent = [{k: r.get(k) for k in ("ts", "symbol", "side", "strategy", "p", "regime", "verdict", "applied",
                                         "taken", "outcome_pnl", "closed_ts", "error")}
                  for r in rows[: min(int(q.get("n", 50)), 500)]]
        return {"enabled": bool(jc.get("enabled")), **report(rows, jc), "recent": recent}

    def config(self) -> dict[str, Any]:
        raw = self.app.cfg.raw
        keep = ("mode", "symbols", "timeframe", "history_bars", "allow_short", "default_strategy", "risk",
                "improve", "schedule")
        out = {k: raw[k] for k in keep}
        out["broker"] = {k: v for k, v in raw["broker"].items() if k not in ("csv_dir",)}
        out["llm"] = {k: v for k, v in raw["llm"].items() if k != "api_key_env"}
        out["jev"] = {k: v for k, v in raw["jev"].items() if k != "api_key_env"}
        out["home"] = str(self.app.cfg.home)
        out["config_path"] = str(self.app.cfg.path) if self.app.cfg.path else None
        return out

    def _symbol(self, q: dict[str, str]) -> str:
        sym = q.get("symbol", "")
        if sym not in self.app.engine.symbols:
            raise ApiError(400, f"unknown symbol {sym!r}; configured: {self.app.engine.symbols}")
        return sym

    def candles(self, q: dict[str, str]) -> dict[str, Any]:
        sym = self._symbol(q)
        bars = max(50, min(int(q.get("bars", 300)), 2000))
        if not self.lock.acquire(timeout=20):
            raise ApiError(503, "The bot is in the middle of a cycle. Try again in a moment.")
        try:
            df = self.app.engine.broker.fetch_ohlcv(sym, self.app.cfg["timeframe"], bars)
            snap = self.app.toolkit.market_snapshot(sym, max(bars, 250))
        finally:
            self.lock.release()
        entry = self.app.engine.book.entry(sym)
        fills = self.app.engine.journal.rows(
            "SELECT ts, side, qty, price, strategy, realized_pnl FROM fills WHERE symbol=? AND status='filled' "
            "ORDER BY id DESC LIMIT 300", (sym,))
        rows = [[int(ts.timestamp() * 1000), *map(float, r)] for ts, r in
                zip(df.index, df[["open", "high", "low", "close", "volume"]].to_numpy(), strict=True)]
        return clean({"symbol": sym, "timeframe": self.app.cfg["timeframe"], "candles": rows, "snapshot": snap,
                      "strategy": {k: v for k, v in entry.items() if k != "history"}, "fills": fills})

    def equity(self, q: dict[str, str]) -> list[dict[str, Any]]:
        rows = self.app.engine.journal.rows("SELECT ts, equity, cash, gross_exposure FROM equity ORDER BY rowid")
        return clean(downsample(rows, max(10, min(int(q.get("limit", 1500)), 5000))))

    # ---- actions -------------------------------------------------------------
    def run_backtest(self, body: dict[str, Any]) -> dict[str, Any]:
        sym = self._symbol(body)
        strat = make(body.get("strategy") or self.app.engine.book.entry(sym)["strategy"],
                     body.get("params") if body.get("strategy") else self.app.engine.book.entry(sym).get("params"))
        bars = max(200, min(int(body.get("bars", 2000)), 10_000))
        cfg = self.app.cfg
        with self.lock:
            df = self.app.engine.broker.fetch_ohlcv(sym, cfg["timeframe"], bars)
        ac = asset_class_of(sym).value
        r = backtest(df, strat, fee_bps=cfg["broker"]["fee_bps"], slippage_bps=cfg["broker"]["slippage_bps"],
                     allow_short=cfg["allow_short"], timeframe=cfg["timeframe"], asset_class=ac)
        bh = (df["close"] / df["close"].iloc[0])
        curve = [[int(t.timestamp() * 1000), float(e), float(b)] for t, e, b in
                 zip(r.equity.index, r.equity.to_numpy(), bh.reindex(r.equity.index).to_numpy(), strict=True)]
        return clean({"result": r.summary(), "buy_and_hold": buy_and_hold(df, cfg["timeframe"], ac),
                      "curve": downsample(curve, 800)})

    def optimize(self, body: dict[str, Any]) -> dict[str, Any]:
        sym = self._symbol(body)
        promote = bool(body.get("promote"))
        with self.lock:
            df = self.app.engine.broker.fetch_ohlcv(sym, self.app.cfg["timeframe"],
                                                    self.app.cfg["improve"]["lookback_bars"])
            rep = self.app.improver.run(sym, df, self.app.engine.book, promote=promote).to_dict()
            if rep["promoted"]:
                self.app.engine.journal.event("promote", f"{sym}: {rep['best']['strategy']}{rep['best']['params']} "
                                              "(from desktop app)", rep)
        self._status_cache = None
        return clean(rep)

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.chat_agent:
            raise ApiError(409, "LLM is disabled. Set llm.enabled: true in config.yaml and restart the backend.")
        msg = str(body.get("message", "")).strip()
        if not msg:
            raise ApiError(400, "empty message")
        tools: list[dict[str, Any]] = []
        self.chat_agent.on_event = lambda kind, data: tools.append(data)
        reply = self.chat_agent.run(msg, tools=CHAT_TOOLS, keep_history=not body.get("reset"))
        return {"reply": reply, "tools": tools}

    def flatten(self, body: dict[str, Any]) -> Any:
        if body.get("confirm") != "FLATTEN":
            raise ApiError(400, 'flatten needs {"confirm": "FLATTEN"}')
        with self.lock:
            out = self.app.engine.flatten("flatten from desktop app")
        self._status_cache = None
        return clean(out)

    def guarded(self, fn: Callable[[], Any]) -> Any:
        with self.lock:
            out = fn()
        self._status_cache = None
        return clean(out)


def make_handler(svc: Service, token: str, port_ref: list[int]) -> type[BaseHTTPRequestHandler]:
    e = svc.app.engine

    GET: dict[str, Callable[[dict[str, str]], Any]] = {
        "/api/status": lambda q: svc.status(),
        "/api/equity": svc.equity,
        "/api/fills": lambda q: clean(e.journal.recent_fills(min(int(q.get("n", 200)), 1000))),
        "/api/decisions": lambda q: clean(e.journal.rows(
            "SELECT * FROM decisions" + (" WHERE symbol=?" if q.get("symbol") else "") + " ORDER BY id DESC LIMIT ?",
            ((q["symbol"],) if q.get("symbol") else ()) + (min(int(q.get("n", 200)), 1000),))),
        "/api/events": lambda q: clean(e.journal.recent_events(min(int(q.get("n", 100)), 500), q.get("kind") or None)),
        "/api/stats": lambda q: clean(e.journal.stats()),
        "/api/book": lambda q: clean({s: e.book.entry(s) for s in e.symbols}),
        "/api/strategies": lambda q: clean(describe()),
        "/api/candles": svc.candles,
        "/api/lessons": lambda q: svc.app.toolkit.lessons.entries(),
        "/api/playbooks": lambda q: svc.app.toolkit.playbooks.index(),
        "/api/playbook": lambda q: {"name": q.get("name"), "text": svc.app.toolkit.playbooks.view(q.get("name", ""))},
        "/api/config": lambda q: clean(svc.config()),
        "/api/jev": lambda q: clean(svc.jev(q)),
    }
    POST: dict[str, Callable[[dict[str, Any]], Any]] = {
        "/api/bot/start": lambda b: svc.start_bot(),
        "/api/bot/stop": lambda b: svc.stop_bot(),
        "/api/cycle": lambda b: svc.guarded(svc.app.engine.cycle),
        "/api/halt": lambda b: svc.guarded(lambda: e.halt(str(b.get("reason") or "halt from desktop app")) or "halted"),
        "/api/resume": lambda b: svc.guarded(lambda: e.resume() or "resumed"),
        "/api/flatten": svc.flatten,
        "/api/rollback": lambda b: svc.guarded(lambda: e.book.rollback(svc._symbol(b)) or "nothing to roll back"),
        "/api/optimize": svc.optimize,
        "/api/backtest": svc.run_backtest,
        "/api/chat": svc.chat,
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = f"hermes-trader/{__version__}"

        def log_message(self, fmt: str, *args: Any) -> None:  # route to logging, quietly
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, obj: Any) -> None:
            body = json.dumps(obj, default=str, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _check(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            if host not in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"):
                self._send(403, {"error": "bad host"})
                return False
            if urlparse(self.path).path == "/api/health":
                return True
            auth = self.headers.get("Authorization") or ""
            if not secrets.compare_digest(auth, f"Bearer {token}"):
                self._send(401, {"error": "missing or bad token",
                                 "hint": "This is the Hermes Trader API for the desktop app, not a web page. Open the "
                                         "app (cd desktop && npm start). For scripts, send 'Authorization: Bearer "
                                         "<token>' using the token in data/api_token."})
                return False
            return True

        def _dispatch(self, routes: dict[str, Callable[[Any], Any]], arg: Any) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                out = {"ok": True, "version": __version__, "mode": svc.app.cfg["mode"]}
                nonce = self.headers.get("X-Challenge") or ""
                if 8 <= len(nonce) <= 128:  # lets the app verify it reached the real backend before sending the token
                    out["proof"] = hmac.new(token.encode(), nonce.encode(), hashlib.sha256).hexdigest()
                self._send(200, out)
                return
            fn = routes.get(path)
            if not fn:
                self._send(404, {"error": f"no route {path}"})
                return
            try:
                self._send(200, {"ok": True, "data": fn(arg)})
            except ApiError as err:
                self._send(err.status, {"ok": False, "error": str(err)})
            except (ValueError, KeyError, TypeError) as err:
                self._send(400, {"ok": False, "error": f"{type(err).__name__}: {err}"})
            except Exception as err:  # noqa: BLE001
                log.exception("API error on %s", path)
                self._send(500, {"ok": False, "error": f"{type(err).__name__}: {err}"})

        def do_GET(self) -> None:  # noqa: N802
            if self._check():
                q = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}
                self._dispatch(GET, q)  # journal reads are serialised inside Journal; broker reads lock themselves

        def do_POST(self) -> None:  # noqa: N802
            if not self._check():
                return
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                self._send(415, {"error": "Content-Type must be application/json"})
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                self._send(413, {"error": "body too large"})
                return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid JSON"})
                return
            if not isinstance(body, dict):
                self._send(400, {"error": "body must be a JSON object"})
                return
            self._dispatch(POST, body)

    return Handler


def write_token(home: Path, token: str) -> Path:
    p = home / "api_token"
    p.unlink(missing_ok=True)  # never reuse an old file and its permissions
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return p


def make_server(app: App, port: int = 8765, token: str | None = None) -> tuple[ThreadingHTTPServer, Service, str]:
    token = token or os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(32)
    svc = Service(app)
    port_ref = [port]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(svc, token, port_ref))
    httpd.daemon_threads = True
    port_ref[0] = httpd.server_address[1]  # resolves port=0 to the real one
    return httpd, svc, token


def watch_stdin(on_eof: Callable[[], None]) -> threading.Thread:
    """The desktop app keeps our stdin open and never writes to it. EOF means the app is gone
    (quit, crash or kill -9), even if a wrapper such as `uv run` sits between us."""

    def loop() -> None:
        try:
            while os.read(0, 4096):
                pass
        except OSError:
            pass
        log.warning("desktop app went away (stdin closed): stopping the bot and exiting")
        on_eof()

    t = threading.Thread(target=loop, name="stdin-watch", daemon=True)
    t.start()
    return t


def serve(app: App, port: int = 8765, run_bot: bool = False) -> None:
    import signal

    httpd, svc, token = make_server(app, port)
    stopping = threading.Event()

    def graceful(reason: str) -> None:
        if stopping.is_set():
            return
        stopping.set()
        was = svc.bot_state()["running"]
        svc.shutdown()
        if was:
            app.engine.journal.event("bot", f"bot stopped: {reason}")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    if os.environ.get(EXIT_ON_EOF_ENV) == "1":
        watch_stdin(lambda: graceful("desktop app went away"))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=graceful, args=("SIGTERM",), daemon=True).start())

    real_port = httpd.server_address[1]
    tok_path = write_token(app.cfg.home, token)
    if run_bot:
        svc.start_bot()
    # one machine-readable line so the desktop app knows we're up
    print(json.dumps({"hermes_trader_api": f"http://127.0.0.1:{real_port}", "token_file": str(tok_path),
                      "mode": app.cfg["mode"]}), flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        graceful("Ctrl-C")
    finally:
        svc.shutdown()
        httpd.server_close()
