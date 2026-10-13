"""Wires config -> broker, engine, improver, memory, LLM agent, notifier. Plus the run-forever scheduler."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from .agent import Agent, Lessons, Playbooks, Toolkit, llm_from_config, make_reviewer, reflect
from .backtest import timeframe_seconds
from .brokers import make_broker
from .config import Config
from .engine import Engine
from .improve import Improver

log = logging.getLogger("hermes_trader")

BUNDLED_PLAYBOOKS = Path(__file__).resolve().parent / "playbooks"


def telegram_notifier(cfg: Config) -> Callable[[str], None]:
    n = cfg["notify"]
    token, chat = cfg.secret(n["telegram_token_env"]), cfg.secret(n["telegram_chat_id_env"])
    if not token or not chat:
        return lambda msg: log.info("notify: %s", msg)

    def send(msg: str) -> None:
        tag = "LIVE" if cfg.is_live else "PAPER"
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": f"[{tag}] {msg}"[:4000]}, timeout=10)
        except requests.RequestException as e:  # notifications must never break trading
            log.warning("telegram failed: %s", e)

    return send


@dataclass
class App:
    cfg: Config
    engine: Engine
    improver: Improver
    toolkit: Toolkit
    agent: Agent | None
    notify: Callable[[str], None]
    jev_error: str | None = None

    def improve_all(self, promote: bool = True) -> list[dict[str, Any]]:
        out = []
        for sym in self.engine.symbols:
            try:
                df = self.engine.broker.fetch_ohlcv(sym, self.cfg["timeframe"], self.cfg["improve"]["lookback_bars"])
                rep = self.improver.run(sym, df, self.engine.book, promote=promote).to_dict()
            except Exception as e:  # noqa: BLE001
                rep = {"symbol": sym, "error": str(e)}
            if rep.get("promoted"):
                b = rep["best"]
                msg = f"{sym}: promoted {b['strategy']}{b['params']} ({rep['reason']})"
                self.engine.journal.event("promote", msg, rep)
                self.notify("🧠 " + msg)
            out.append(rep)
        self.engine.meta["last_improve"] = datetime.now(timezone.utc).isoformat()
        self.engine.save()
        return out

    def maybe_reflect(self) -> str | None:
        if not self.agent:
            return None
        j = self.engine.journal
        done = self.engine.meta.get("reflected_at_closed_trades", 0)
        if j.closed_trade_count() - done < self.cfg["improve"]["reflect_after_trades"]:
            return None
        try:
            out = reflect(self.agent)
            self.notify("🪞 Reflection:\n" + out[:1500])
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("reflection failed: %s", e)
            return None

    def cycle_seconds(self) -> float:
        tf_s = timeframe_seconds(self.cfg["timeframe"])
        return float((self.cfg["schedule"].get("cycle_minutes") or tf_s / 60) * 60)

    def next_wake(self, now: float | None = None) -> float:
        """Epoch seconds of the next cycle: 5s after the next bar close, so the venue has the candle."""
        every = self.cycle_seconds()
        now = time.time() if now is None else now
        return (now // every + 1) * every + 5

    def tick(self) -> dict[str, Any]:
        """One scheduler step: re-optimise if due, trade one cycle, reflect if due."""
        improve_every = self.cfg["schedule"]["improve_every_hours"] * 3600
        last_imp = self.engine.meta.get("last_improve")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_imp)).total_seconds() if last_imp else 1e12
        if age >= improve_every:
            self.improve_all()
        rep = self.engine.cycle()
        log.info("cycle: %s", {s: v.get("action") for s, v in rep["symbols"].items()})
        self.maybe_reflect()
        return rep

    def run_forever(self, once: bool = False) -> None:
        self.notify(f"Hermes Trader started: {self.cfg['mode']} via {self.engine.broker.name}, "
                    f"{', '.join(self.engine.symbols)} @ {self.cfg['timeframe']}")
        while True:
            self.tick()
            if once:
                return
            time.sleep(max(1.0, self.next_wake() - time.time()))


def build(cfg: Config, confirm: Callable[[str], bool] | None = None,
          on_event: Callable[[str, Any], None] | None = None) -> App:
    broker = make_broker(cfg)
    notify = telegram_notifier(cfg)
    engine = Engine(cfg, broker, notify=notify)
    if cfg["filters"].get("enabled", True):
        from .filters import EntryFilters

        engine.filters = EntryFilters(cfg["filters"], cfg["risk"], broker, cfg["timeframe"])
        vc = cfg["filters"].get("vol") or {}
        if vc.get("enabled", True) and vc.get("iv", True):
            from .vol import ImpliedVol

            engine.filters.iv = ImpliedVol()
    b = cfg["broker"]
    improver = Improver(cfg["improve"], fee_bps=b["fee_bps"], slippage_bps=b["slippage_bps"],
                        timeframe=cfg["timeframe"], allow_short=cfg["allow_short"])
    lessons = Lessons(cfg.home / "LESSONS.md")
    playbooks = Playbooks(cfg.home / "playbooks", [BUNDLED_PLAYBOOKS])
    toolkit = Toolkit(engine, improver, lessons, playbooks, confirm=confirm)
    jev_error = None
    if cfg["jev"].get("enabled"):
        from .jev import JevClient, JevError, JevReviewer

        try:
            engine.jev = JevReviewer(JevClient.from_config(cfg["jev"]), cfg["jev"], cfg["timeframe"], engine.journal,
                                     engine.book, lessons)
            if (cfg["jev"].get("checks") or {}).get("enabled", True):
                from .jev_checks import JevChecker

                engine.jev_checks = JevChecker(engine.jev.client, cfg["jev"], cfg["timeframe"], lessons)
        except (JevError, ValueError) as e:  # trade without JEV rather than not at all
            jev_error = str(e)
            log.warning("JEV disabled: %s", e)
            engine.journal.event("error", f"JEV disabled: {e}")
    agent = None
    lc = cfg["llm"]
    if lc.get("enabled"):
        llm = llm_from_config(lc)
        agent = Agent(llm, toolkit, lc.get("max_tool_iterations", 12), on_event)
        if lc.get("trade_review", True):
            engine.reviewer = make_reviewer(llm, toolkit)
    return App(cfg, engine, improver, toolkit, agent, notify, jev_error)
