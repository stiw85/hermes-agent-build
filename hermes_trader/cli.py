"""hermes-trader command line."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _p(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _confirm(prompt: str) -> bool:
    try:
        return input(f"\n⚠️  CONFIRM ORDER: {prompt}\n   type 'yes' to send: ").strip().lower() == "yes"
    except EOFError:
        return False


def cmd_init(a: argparse.Namespace) -> None:
    for src, dst in (("config.example.yaml", "config.yaml"), ("env.example", ".env")):
        s, d = TEMPLATES / src, Path(dst)
        if d.exists():
            print(f"exists: {d}")
        elif s.exists():
            shutil.copy(s, d)
            print(f"created {d}")
    print("Next: edit config.yaml, then `hermes-trader backtest BTC/USDT` and `hermes-trader run --once`.")


def cmd_llm(cfg: Any) -> int:
    """One real call with one tool offered: proves auth, URL, model id and tool calling in one go."""
    from .agent.llm import LLMError, detect_provider, llm_from_config

    lc = cfg["llm"]
    provider = detect_provider(lc)
    llm = llm_from_config(lc)
    where = {"provider": provider, "url": llm.url, "model": llm.model, "enabled_in_config": bool(lc.get("enabled"))}
    tool = {"type": "function", "function": {
        "name": "get_price", "description": "Latest price for a market symbol.",
        "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}
    msgs = [{"role": "system", "content": "You are a test harness. Use the tool when asked."},
            {"role": "user", "content": "Call get_price for BTC/USDT."}]
    try:
        first = llm.chat(msgs, tools=[tool])
        calls = first.get("tool_calls") or []
        if calls:
            msgs.append({"role": "assistant", "content": first.get("content") or "", "tool_calls": calls})
            msgs.append({"role": "tool", "tool_call_id": calls[0].get("id", ""), "content": '{"price": 65000}'})
            final = llm.chat(msgs, tools=[tool]).get("content") or ""
        else:
            final = first.get("content") or ""
    except LLMError as err:
        print(f"❌ {err}", file=sys.stderr)
        _p(where)
        return 2
    _p({**where, "ok": True, "tool_calling": bool(calls), "reply": final[:200]})
    if not calls:
        print("⚠️  The model answered but did not call the tool: chat/reflect need a tool-calling model.",
              file=sys.stderr)
    if not lc.get("enabled"):
        print("ℹ️  Works. Set llm.enabled: true in config.yaml and restart the backend to use it.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("hermes-trader", description="Lean self-improving trading agent")
    ap.add_argument("-c", "--config", help="config file (default: ./config.yaml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create config.yaml and .env from examples")
    sub.add_parser("status", help="equity, positions, risk state")
    b = sub.add_parser("backtest", help="backtest a symbol")
    b.add_argument("symbol")
    b.add_argument("--strategy")
    b.add_argument("--params", default="{}", help='JSON, e.g. \'{"fast":10,"slow":50}\'')
    b.add_argument("--bars", type=int, default=2000)
    o = sub.add_parser("optimize", help="walk-forward strategy search")
    o.add_argument("symbol", nargs="?")
    o.add_argument("--promote", action="store_true", help="promote winners that pass the gate")
    r = sub.add_parser("run", help="trade on every bar close")
    r.add_argument("--once", action="store_true", help="single cycle then exit (cron-friendly)")
    sub.add_parser("flatten", help="close all positions now")
    h = sub.add_parser("halt", help="stop opening new positions")
    h.add_argument("reason", nargs="?", default="manual halt")
    sub.add_parser("resume", help="clear halt and reset drawdown baseline")
    rb = sub.add_parser("rollback", help="revert a symbol to its previous strategy")
    rb.add_argument("symbol")
    sub.add_parser("book", help="show the strategy book")
    sub.add_parser("journal", help="live performance stats")
    sub.add_parser("lessons", help="show learned lessons")
    sub.add_parser("reflect", help="run an LLM self-review now")
    ch = sub.add_parser("chat", help="talk to the trading agent")
    ch.add_argument("message", nargs="*")
    jv = sub.add_parser("jev", help="JEV decision-model report (shadow/gate calibration)")
    jv.add_argument("--test", action="store_true", help="make one live JEV call to check the key and endpoint")
    sub.add_parser("llm", help="make one live LLM call to check the key, endpoint, model and tool calling")
    sv = sub.add_parser("serve", help="local API for the desktop app (127.0.0.1 only)")
    sv.add_argument("--port", type=int, default=8765, help="0 = pick a free port")
    sv.add_argument("--run", action="store_true", help="start the trading loop immediately")
    d = sub.add_parser("download", help="save history to CSV (for data_source: csv)")
    d.add_argument("symbol")
    d.add_argument("--bars", type=int, default=5000)
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "init":
        cmd_init(a)
        return 0

    from .runtime import build  # heavy imports after arg parsing

    try:
        cfg = load_config(a.config)
    except ConfigError as err:
        print(f"❌ {err}", file=sys.stderr)
        return 2
    if a.cmd == "llm":
        return cmd_llm(cfg)
    interactive = a.cmd == "chat"
    app = build(cfg, confirm=_confirm if interactive else None,
                on_event=(lambda k, v: print(f"  · {v['name']}({json.dumps(v['args'])[:120]})")) if interactive
                else None)
    e = app.engine
    if cfg.is_live:
        print("⚠️  LIVE MODE — real orders will be sent.", file=sys.stderr)

    if a.cmd == "status":
        _p(e.status())
    elif a.cmd == "backtest":
        if a.symbol not in e.symbols:
            cfg.raw["symbols"] = [*e.symbols, a.symbol]
        strat = a.strategy or e.book.entry(a.symbol)["strategy"]
        params = json.loads(a.params) or ({} if a.strategy else e.book.entry(a.symbol).get("params"))
        _p(app.toolkit.run_backtest(a.symbol, strat, params, a.bars))
    elif a.cmd == "optimize":
        syms = [a.symbol] if a.symbol else e.symbols
        if a.symbol:
            cfg.raw["symbols"] = list(dict.fromkeys([*e.symbols, a.symbol]))
        out = []
        for s in syms:
            df = e.broker.fetch_ohlcv(s, cfg["timeframe"], cfg["improve"]["lookback_bars"])
            rep = app.improver.run(s, df, e.book, promote=a.promote).to_dict()
            if rep["promoted"]:
                e.journal.event("promote", f"{s}: {rep['best']['strategy']}{rep['best']['params']}", rep)
            out.append(rep)
        _p(out)
    elif a.cmd == "run":
        try:
            app.run_forever(once=a.once)
        except KeyboardInterrupt:
            print("stopped")
    elif a.cmd == "flatten":
        _p(e.flatten())
    elif a.cmd == "halt":
        e.halt(a.reason)
        print("halted")
    elif a.cmd == "resume":
        e.resume()
        print("resumed")
    elif a.cmd == "rollback":
        _p(e.book.rollback(a.symbol) or "nothing to roll back")
    elif a.cmd == "book":
        _p({s: e.book.entry(s) for s in e.symbols})
    elif a.cmd == "journal":
        _p(e.journal.stats())
    elif a.cmd == "lessons":
        print(app.toolkit.lessons.render())
    elif a.cmd in ("reflect", "chat"):
        if not app.agent:
            print("LLM disabled: set llm.enabled: true and LLM_API_KEY in .env", file=sys.stderr)
            return 2
        if a.cmd == "reflect":
            from .agent import reflect

            print(reflect(app.agent))
        elif a.message:
            print(app.agent.run(" ".join(a.message)))
        else:
            print("Hermes Trader chat — Ctrl-D to exit")
            while True:
                try:
                    msg = input("\nyou> ").strip()
                except EOFError:
                    break
                if msg:
                    print("\nhermes>", app.agent.run(msg, keep_history=True))
    elif a.cmd == "jev":
        from .jev import JevClient, JevReviewer, report

        jc = cfg["jev"]
        if app.jev_error and not a.test:
            print(f"⚠️  {app.jev_error}", file=sys.stderr)
        if a.test:
            from .jev import JevError

            try:
                rev = JevReviewer(JevClient.from_config(jc), {**jc, "mode": jc.get("mode", "shadow")})
            except JevError as err:
                print(f"❌ {err}", file=sys.stderr)
                return 2
            sym = e.symbols[0]
            df = e.broker.fetch_ohlcv(sym, cfg["timeframe"], 300)
            from .jev import build_state
            from .models import Order, Side
            from .risk import RiskDecision

            sig = e.book.strategy_for(sym).signal(sym, df)
            dec = RiskDecision(Order(sym, Side.BUY, 1.0), True, [], 1000.0, 0.0)
            try:
                v = rev.score(build_state(sig, dec, e.broker.account(e.symbols), df, cfg["timeframe"], {}, []), "buy")
            except JevError as err:
                print(f"❌ JEV call to {jc['url']} failed: {err}", file=sys.stderr)
                return 2
            _p({"ok": True, "endpoint": jc["url"], "model": v.model, "symbol": sym, "p_worth_taking_long": v.p,
                "regime": v.regime, "gate_would": v.verdict, "cost_usd": v.cost})
        else:
            from .jev_checks import check_report

            _p({"enabled": bool(jc.get("enabled")), "entry_gate": report(e.journal.jev_rows(), jc),
                "per_bar_checks": check_report(e.journal.jev_check_rows(), jc)})
    elif a.cmd == "serve":
        from .server import serve

        serve(app, a.port, run_bot=a.run)
    elif a.cmd == "download":
        from .data import save_csv

        df = e.broker.fetch_ohlcv(a.symbol, cfg["timeframe"], a.bars)
        print(save_csv(df, cfg["broker"]["csv_dir"], a.symbol, cfg["timeframe"]), len(df), "bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
