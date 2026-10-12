"""Deterministic self-improvement: walk-forward strategy selection with promotion gates.

For each symbol:
  1. fetch `lookback_bars` of history, split into train (first 70%) and test (last 30%)
  2. grid-search every candidate strategy on TRAIN, keep the top few by score
  3. re-score those on unseen TEST data (indicators warm up on train, never scored twice)
  4. re-score the incumbent on the same TEST window
  5. promote only if the challenger beats the incumbent by `min_improvement`,
     has >= `min_trades`, and drawdown <= `max_drawdown`

The LLM can *ask* for an optimisation or a promotion, but it goes through these same gates.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .backtest import BacktestResult, backtest
from .book import StrategyBook
from .brokers.base import asset_class_of
from .strategies import REGISTRY, make


@dataclass
class Candidate:
    strategy: str
    params: dict[str, Any]
    train: dict[str, Any]
    test: dict[str, Any]
    score: float


@dataclass
class ImproveReport:
    symbol: str
    incumbent: dict[str, Any]
    incumbent_score: float
    best: Candidate | None
    promoted: bool
    reason: str
    leaderboard: list[Candidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def c(x: Candidate | None) -> dict[str, Any] | None:
            if not x:
                return None
            return {"strategy": x.strategy, "params": x.params, "score": round(x.score, 3),
                    "test": x.test, "train_sharpe": x.train.get("sharpe")}

        return {"symbol": self.symbol, "incumbent": self.incumbent,
                "incumbent_score": round(self.incumbent_score, 3) if math.isfinite(self.incumbent_score) else None,
                "best": c(self.best), "promoted": self.promoted, "reason": self.reason,
                "leaderboard": [c(x) for x in self.leaderboard[:5]]}


class Improver:
    def __init__(self, cfg: dict[str, Any], *, fee_bps: float, slippage_bps: float, timeframe: str,
                 allow_short: bool, seed: int = 7) -> None:
        self.c = cfg
        self.bt_kw = {"fee_bps": fee_bps, "slippage_bps": slippage_bps, "timeframe": timeframe,
                      "allow_short": allow_short}
        self.rng = random.Random(seed)

    def _bt(self, df: pd.DataFrame, name: str, params: dict[str, Any], eval_from: int, symbol: str) -> BacktestResult:
        return backtest(df, make(name, params), eval_from=eval_from,
                        asset_class=asset_class_of(symbol).value, **self.bt_kw)

    def evaluate(self, symbol: str, df: pd.DataFrame, name: str, params: dict[str, Any]) -> Candidate:
        split = int(len(df) * self.c["train_fraction"])
        train = self._bt(df.iloc[:split], name, params, 0, symbol)
        test = self._bt(df, name, params, split, symbol)
        return Candidate(name, params, train.summary(), test.summary(), test.score(self.c["min_trades"] // 2))

    def search(self, symbol: str, df: pd.DataFrame, strategies: list[str] | None = None) -> list[Candidate]:
        names = [s for s in (strategies or self.c["strategies"]) if s in REGISTRY]
        split = int(len(df) * self.c["train_fraction"])
        train_df = df.iloc[:split]
        per = max(4, self.c["max_candidates"] // max(1, len(names)))
        shortlist: list[tuple[float, str, dict[str, Any]]] = []
        for name in names:
            space = REGISTRY[name].param_space()
            if len(space) > per:
                space = self.rng.sample(space, per)
            scored = []
            for p in space:
                strat = make(name, p)
                if len(train_df) < strat.warmup() * 2 + 10:
                    continue
                r = self._bt(train_df, name, p, 0, symbol)
                scored.append((r.score(self.c["min_trades"]), name, p))
            scored.sort(key=lambda t: t[0], reverse=True)
            shortlist.extend(s for s in scored[:3] if math.isfinite(s[0]))
        out = [self.evaluate(symbol, df, n, p) for _, n, p in shortlist]
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def gate(self, cand: Candidate, incumbent_score: float) -> tuple[bool, str]:
        t = cand.test
        if t["trades"] < self.c["min_trades"]:
            return False, f"only {t['trades']} test trades (< {self.c['min_trades']})"
        if t["max_drawdown"] > self.c["max_drawdown"]:
            return False, f"test drawdown {t['max_drawdown']:.1%} > {self.c['max_drawdown']:.0%}"
        if t["sharpe"] <= 0 or t["total_return"] <= 0:
            return False, f"test sharpe {t['sharpe']:.2f} / return {t['total_return']:.1%} not positive"
        if math.isfinite(incumbent_score) and cand.score < incumbent_score + self.c["min_improvement"]:
            return False, f"score {cand.score:.2f} doesn't beat incumbent {incumbent_score:.2f} + {self.c['min_improvement']}"
        return True, f"score {cand.score:.2f} vs incumbent {incumbent_score:.2f}"

    def run(self, symbol: str, df: pd.DataFrame, book: StrategyBook, promote: bool = True,
            strategies: list[str] | None = None) -> ImproveReport:
        inc = book.entry(symbol)
        try:
            inc_c = self.evaluate(symbol, df, inc["strategy"], inc.get("params") or {})
            inc_score = inc_c.score
        except ValueError:
            inc_score = -math.inf
        board = self.search(symbol, df, strategies)
        best = board[0] if board else None
        same = best and best.strategy == inc["strategy"] and best.params == inc.get("params")
        if not best:
            return ImproveReport(symbol, inc, inc_score, None, False, "no viable candidates", board)
        if same:
            return ImproveReport(symbol, inc, inc_score, best, False, "incumbent is already best", board)
        ok, why = self.gate(best, inc_score)
        if ok and promote:
            book.promote(symbol, best.strategy, best.params,
                         {"test": best.test, "score": round(best.score, 3), "bars": len(df)}, source="walk-forward")
        return ImproveReport(symbol, inc, inc_score, best, ok and promote, why, board)
