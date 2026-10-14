"""JEV checks that run every bar, for every symbol: one request, several independent questions.

  regime         (choice) trending_up / trending_down / ranging / volatile
  strategy_fits  (noul)   is the active strategy's style suited to this market right now?
  exit_now       (noul)   only with an open position: has the reason to hold gone away?

Every answer is scored later against what price actually did over the next `horizon_bars`:
  regime rows: the strategy's forward return in the direction it wanted (low fit should mean worse)
  exit rows:   the forward return of simply holding (a high exit probability should mean holding lost)
Price keeps moving whether or not we acted, so this stays measurable in act mode too.

Modes (jev.checks.mode):
  shadow - record and score only
  act    - fit < regime_block_below: the strategy stands aside (no NEW risk; exits still work)
           exit >= exit_above: close the position (and no re-entry until the signal resets)
Both actions can only reduce risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .jev import REGIMES, STRATEGY_STYLE, JevClient, JevError, market_facts
from .models import Position, Signal

DEFAULTS = {
    "enabled": True,
    "mode": "shadow",  # shadow | act
    "regime_block_below": 0.35,
    "exit_above": 0.70,
    "horizon_bars": 6,
    "min_resolved": 50,
}


def check_questions(strategy: str, position_side: str | None) -> dict[str, Any]:
    style = STRATEGY_STYLE.get(strategy, strategy)
    q: dict[str, Any] = {
        "regime": {"type": "choice", "instructions": "Which market regime is this symbol in right now?",
                   "criteria": dict(REGIMES)},
        "strategy_fits": {
            "type": "noul",
            "instructions": (f"A {style} strategy is well suited to how this market is behaving right now: its "
                             "signals are likely to work over the next few bars."),
            "criteria": {
                "true": "The market's current behaviour is the kind this style of strategy profits from.",
                "false": "The market is behaving in a way that typically makes this style of strategy lose "
                         "(for example mean reversion in a strong trend, or trend-following in a choppy range).",
            },
        },
    }
    if position_side:
        q["exit_now"] = {
            "type": "noul",
            "instructions": (f"The reason for holding this {position_side} position has gone away: closing it now "
                             "is better than holding it for the next few bars."),
            "criteria": {
                "true": "Momentum or trend has turned against the position, or it is stalling in a way that "
                        "usually leads to giving back gains or deeper losses.",
                "false": "The move behind the position is intact; holding is still reasonable.",
            },
        }
    return q


def build_check_state(sig: Signal, pos: Position | None, df: pd.DataFrame, timeframe: str,
                      lessons: list[str]) -> dict[str, Any]:
    want = "long" if sig.target > 0 else "short" if sig.target < 0 else "flat"
    state: dict[str, Any] = {
        "market": market_facts(sig.symbol, df, timeframe),
        "strategy": {"name": sig.strategy, "style": STRATEGY_STYLE.get(sig.strategy, sig.strategy),
                     "currently_wants": want, "signal": sig.reason[:300]},
        "lessons_from_past_trading": lessons[-6:],
    }
    if pos and pos.qty:
        px = pos.market_price or float(df["close"].iloc[-1])
        side = 1 if pos.qty > 0 else -1
        upnl = side * (px / pos.avg_price - 1) if pos.avg_price else 0.0
        st: dict[str, Any] = {"side": "long" if side > 0 else "short",
                              "unrealised_result_pct": round(100 * upnl, 2)}
        if sig.atr and px:
            st["unrealised_result_in_atr"] = round(upnl * px / sig.atr, 2)
        state["open_position"] = st
    return state


@dataclass
class CheckResult:
    regime: str | None
    regime_conf: float | None
    fit_p: float | None
    exit_p: float | None
    cost: float
    model: str


class JevChecker:
    def __init__(self, client: JevClient, jev_cfg: dict[str, Any], timeframe: str = "1h", lessons: Any = None) -> None:
        self.client = client
        self.c = {**DEFAULTS, **(jev_cfg.get("checks") or {})}
        self.timeframe = timeframe
        self.lessons = lessons
        if self.c["mode"] not in ("shadow", "act"):
            raise ValueError("jev.checks.mode must be shadow or act")
        if not (0 <= self.c["regime_block_below"] <= 1 and 0 <= self.c["exit_above"] <= 1):
            raise ValueError("jev.checks thresholds must be between 0 and 1")

    @property
    def acting(self) -> bool:
        return self.c["mode"] == "act"

    def check(self, sig: Signal, pos: Position | None, df: pd.DataFrame) -> CheckResult:
        side = None if not (pos and pos.qty) else ("long" if pos.qty > 0 else "short")
        lessons = self.lessons.entries() if self.lessons is not None else []
        resp = self.client.decide(build_check_state(sig, pos, df, self.timeframe, lessons),
                                  check_questions(sig.strategy, side))
        a = resp["answers"]

        def noul(name: str) -> float | None:
            v = (a.get(name) or {}).get("noul")
            return float(v) if isinstance(v, (int, float)) and 0 <= v <= 1 else None

        fit = noul("strategy_fits")
        if fit is None:
            raise JevError(f"Jev returned no strategy_fits probability: {a.get('strategy_fits')}")
        r = a.get("regime") or {}
        return CheckResult(regime=r.get("choice"), regime_conf=r.get("confidence"), fit_p=fit,
                           exit_p=noul("exit_now") if side else None,
                           cost=float((resp.get("usage") or {}).get("cost") or 0.0),
                           model=str(resp.get("model") or self.client.model))


def _bucket_table(rows: list[dict[str, Any]], edges: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    out = []
    for name, lo, hi in edges:
        rs = [r for r in rows if lo <= r["p"] < hi]
        f = [r["fwd_ret"] for r in rs]
        out.append({"bucket": name, "n": len(rs),
                    "avg_fwd_pct": round(100 * sum(f) / len(f), 3) if f else None,
                    "up_share": round(sum(1 for x in f if x > 0) / len(f), 3) if f else None})
    return out


def check_report(rows: list[dict[str, Any]], jev_cfg: dict[str, Any]) -> dict[str, Any]:
    c = {**DEFAULTS, **(jev_cfg.get("checks") or {})}
    done = [r for r in rows if r.get("resolved_ts") and r.get("fwd_ret") is not None and r.get("p") is not None]
    reg = [r for r in done if r["kind"] == "regime" and r.get("side_sign")]
    ext = [r for r in done if r["kind"] == "exit"]
    b, x = c["regime_block_below"], c["exit_above"]
    reg_b = _bucket_table(reg, [(f"fit < {b:.2f} (would stand aside)", 0, b), (f"{b:.2f}–0.50", b, 0.5),
                                ("0.50–0.65", 0.5, 0.65), ("fit ≥ 0.65", 0.65, 1.01)])
    ext_b = _bucket_table(ext, [("exit < 0.30", 0, 0.3), ("0.30–0.50", 0.3, 0.5), (f"0.50–{x:.2f}", 0.5, x),
                                (f"exit ≥ {x:.2f} (would close)", x, 1.01)])
    n_min = int(c["min_resolved"])

    def verdict_regime() -> str:
        if len(reg) < n_min:
            return f"Keep shadowing: {len(reg)}/{n_min} regime checks scored."
        low, top = reg_b[0], reg_b[-1]
        if low["n"] >= 5 and low["avg_fwd_pct"] is not None and low["avg_fwd_pct"] < 0 and \
                (top["avg_fwd_pct"] is None or low["avg_fwd_pct"] < top["avg_fwd_pct"]):
            return (f"Low-fit bars averaged {low['avg_fwd_pct']:+.3f}% over the next {c['horizon_bars']} bars vs "
                    f"{top['avg_fwd_pct'] if top['avg_fwd_pct'] is not None else 'n/a'}% for high-fit: "
                    "standing aside would have helped. Consider jev.checks.mode: act.")
        return "No edge yet: low-fit bars did not do worse than high-fit ones."

    def verdict_exit() -> str:
        if len(ext) < max(10, n_min // 2):
            return f"Keep shadowing: {len(ext)}/{max(10, n_min // 2)} exit checks scored."
        hi = ext_b[-1]
        if hi["n"] >= 5 and hi["avg_fwd_pct"] is not None and hi["avg_fwd_pct"] < 0:
            return (f"When Jev said exit (≥{x:.2f}), holding then returned {hi['avg_fwd_pct']:+.3f}% on average: "
                    "closing would have helped (before fees). Consider jev.checks.mode: act.")
        return "No edge yet: positions Jev wanted to exit did not go on to lose."

    regimes: dict[str, int] = {}
    for r in rows:
        if r["kind"] == "regime" and r.get("regime"):
            regimes[r["regime"]] = regimes.get(r["regime"], 0) + 1
    return {
        "mode": c["mode"], "horizon_bars": c["horizon_bars"], "regime_block_below": b, "exit_above": x,
        "checks": len(rows), "errors": sum(1 for r in rows if r.get("error")),
        "cost_usd": round(sum(r.get("cost") or 0 for r in rows), 6),
        "regime": {"scored": len(reg), "buckets": reg_b, "recommendation": verdict_regime(),
                   "seen": regimes},
        "exit": {"scored": len(ext), "buckets": ext_b, "recommendation": verdict_exit()},
    }
