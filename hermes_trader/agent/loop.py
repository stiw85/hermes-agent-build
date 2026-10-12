"""Agent loop (tool calling), trade reviewer, and the reflection pass."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import pandas as pd

from ..brokers.base import asset_class_of
from ..models import Account, Signal
from ..risk import RiskDecision
from .llm import LLM, parse_json
from .prompts import REFLECT_PROMPT, REVIEW_PROMPT, system_prompt
from .tools import Toolkit, market_snapshot

log = logging.getLogger("hermes_trader.agent")


class Agent:
    def __init__(self, llm: LLM, toolkit: Toolkit, max_iterations: int = 12,
                 on_event: Callable[[str, Any], None] | None = None) -> None:
        self.llm = llm
        self.tk = toolkit
        self.max_iter = max_iterations
        self.on_event = on_event or (lambda kind, data: None)
        self.messages: list[dict[str, Any]] = []

    def _system(self, context: str = "") -> dict[str, str]:
        home = self.tk.e.cfg.home
        return {"role": "system",
                "content": system_prompt(home, self.tk.lessons.render(), self.tk.playbooks.index(), context)}

    def run(self, user: str, context: str = "", tools: list[str] | None = None, keep_history: bool = False) -> str:
        if not keep_history or not self.messages:
            self.messages = [self._system(context)]
        else:
            self.messages[0] = self._system(context)  # refresh lessons/playbooks
        self.messages.append({"role": "user", "content": user})
        schemas = self.tk.schemas(tools)
        for _ in range(self.max_iter):
            msg = self.llm.chat(self.messages, tools=schemas)
            calls = msg.get("tool_calls") or []
            self.messages.append({"role": "assistant", "content": msg.get("content") or "",
                                  **({"tool_calls": calls} if calls else {})})
            if not calls:
                return msg.get("content") or ""
            for c in calls:
                fn = c.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                self.on_event("tool", {"name": fn.get("name"), "args": args})
                out = self.tk.call(fn.get("name", ""), args)
                self.messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
        # out of budget: ask for a final answer without tools
        self.messages.append({"role": "user", "content": "Tool budget exhausted. Summarise now."})
        return self.llm.chat(self.messages).get("content") or ""


def make_reviewer(llm: LLM, toolkit: Toolkit) -> Callable[[Signal, RiskDecision, Account, pd.DataFrame], dict]:
    """One-shot LLM check before the engine adds risk. Can shrink or veto, never enlarge."""

    def review(sig: Signal, dec: RiskDecision, acct: Account, df: pd.DataFrame) -> dict[str, Any]:
        cfg = toolkit.e.cfg
        snap = market_snapshot(df, cfg["timeframe"], asset_class_of(sig.symbol).value)
        o = dec.order
        ctx = {
            "symbol": sig.symbol, "strategy": sig.strategy, "signal": sig.reason, "target": sig.target,
            "order": {"side": o.side.value, "qty": o.qty, "notional": round(o.qty * sig.price, 2)} if o else None,
            "risk_notes": dec.notes, "equity": round(acct.equity, 2),
            "position_now": round(dec.current_notional, 2), "market": snap,
            "book_entry": {k: v for k, v in toolkit.e.book.entry(sig.symbol).items() if k != "history"},
        }
        msgs = [
            {"role": "system", "content": system_prompt(cfg.home, toolkit.lessons.render(),
                                                        toolkit.playbooks.index())},
            {"role": "user", "content": REVIEW_PROMPT + "\n" + json.dumps(ctx, default=str)},
        ]
        reply = llm.chat(msgs, json_mode=True).get("content") or ""
        out = parse_json(reply)
        out["verdict"] = str(out.get("verdict", "approve")).lower()
        if out["verdict"] not in ("approve", "reduce", "veto"):
            out["verdict"] = "approve"
        if out["verdict"] == "approve":
            out["size_mult"] = 1.0
        return out

    return review


REFLECT_TOOLS = ["journal_stats", "recent_trades", "recent_decisions", "strategy_book", "market_snapshot",
                 "run_backtest", "optimize", "promote_strategy", "rollback_strategy", "memory", "playbook",
                 "list_strategies", "get_portfolio"]


def reflect(agent: Agent) -> str:
    """Hermes-style background review: learn from the journal, update memory/playbooks/strategy book."""
    out = agent.run(REFLECT_PROMPT, tools=REFLECT_TOOLS)
    j = agent.tk.e.journal
    j.event("reflect", out[:2000])
    agent.tk.e.meta["reflected_at_closed_trades"] = j.closed_trade_count()
    agent.tk.e.save()
    return out
