"""Deterministic self-improvement: walk-forward strategy selection with promotion gates.

For each symbol:
  1. fetch `lookback_bars` of history; split into TRAIN (first 70%) and HOLDOUT (last 30%)
  2. grid-search every candidate strategy on TRAIN only and pick ONE challenger by train score
  3. score that single challenger and the incumbent once on HOLDOUT (indicators warm up on
     train bars, which are never scored twice)
  4. promote only if the challenger beats the incumbent by `min_improvement`,
     has >= `min_trades`, and drawdown <= `max_drawdown`

Selection never looks at the holdout, so the gate is a genuine out-of-sample test.
The LLM can *ask* for a promotion, but it goes through the same gate and is rate-limited
per symbol so it can't keep re-rolling candidates against the same holdout.
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
    train_score: float
    test: dict[str, Any] = field(default_factory=dict)
    score: float = -math.inf  # holdout score; only set for the one challenger and the incumbent


@dataclass
class ImproveReport:
    symbol: str
    incumbent: dict[str, Any]
    incumbent_score: float
    best: Candidate | None
    promoted: bool
    reason: str
    leaderboard: list[Candidate] = field(default_factory=list)
    passes: bool = False  # the challenger cleared the holdout gate (promoted or not)

    def to_dict(self) -> dict[str, Any]:
        def c(x: Candidate | None) -> dict[str, Any] | None:
            if not x:
                return None
            d = {"strategy": x.strategy, "params": x.params, "train_score": round(x.train_score, 3),
                 "train": {k: x.train.get(k) for k in ("sharpe", "total_return", "max_drawdown", "trades")}}
            if x.test:
                d.update(holdout=x.test, holdout_score=round(x.score, 3) if math.isfinite(x.score) else None)
            return d

        return {"symbol": self.symbol, "incumbent": self.incumbent,
                "incumbent_score": round(self.incumbent_score, 3) if math.isfinite(self.incumbent_score) else None,
                "best": c(self.best), "promoted": self.promoted, "passes": self.passes, "reason": self.reason,
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

    def split(self, df: pd.DataFrame) -> int:
        return int(len(df) * self.c["train_fraction"])

    def evaluate(self, symbol: str, df: pd.DataFrame, name: str, params: dict[str, Any]) -> Candidate:
        """Train metrics plus ONE holdout score. Use only for a chosen challenger and the incumbent."""
        split = self.split(df)
        train = self._bt(df.iloc[:split], name, params, 0, symbol)
        test = self._bt(df, name, params, split, symbol)
        return Candidate(name, params, train.summary(), train.score(self.c["min_trades"]), test.summary(),
                         test.score(self.c["min_trades"] // 2))

    def search(self, symbol: str, df: pd.DataFrame, strategies: list[str] | None = None) -> list[Candidate]:
        """Rank candidates by TRAIN score only. Holdout data is never touched here."""
        names = [s for s in (strategies or self.c["strategies"]) if s in REGISTRY]
        train_df = df.iloc[: self.split(df)]
        per = max(4, self.c["max_candidates"] // max(1, len(names)))
        out: list[Candidate] = []
        for name in names:
            space = REGISTRY[name].param_space()
            if len(space) > per:
                space = self.rng.sample(space, per)
            for p in space:
                if len(train_df) < make(name, p).warmup() * 2 + 10:
                    continue
                r = self._bt(train_df, name, p, 0, symbol)
                sc = r.score(self.c["min_trades"])
                if math.isfinite(sc):
                    out.append(Candidate(name, p, r.summary(), sc))
        out.sort(key=lambda c: c.train_score, reverse=True)
        return out

    def gate(self, cand: Candidate, incumbent_score: float) -> tuple[bool, str]:
        t = cand.test
        if t["trades"] < self.c["min_trades"]:
            return False, f"only {t['trades']} holdout trades (< {self.c['min_trades']})"
        if t["max_drawdown"] > self.c["max_drawdown"]:
            return False, f"holdout drawdown {t['max_drawdown']:.1%} > {self.c['max_drawdown']:.0%}"
        if t["sharpe"] <= 0 or t["total_return"] <= 0:
            return False, f"holdout sharpe {t['sharpe']:.2f} / return {t['total_return']:.1%} not positive"
        if math.isfinite(incumbent_score) and cand.score < incumbent_score + self.c["min_improvement"]:
            return False, f"holdout score {cand.score:.2f} doesn't beat incumbent {incumbent_score:.2f} + {self.c['min_improvement']}"
        return True, f"holdout score {cand.score:.2f} vs incumbent {incumbent_score:.2f}"

    def incumbent_score(self, symbol: str, df: pd.DataFrame, entry: dict[str, Any]) -> float:
        try:
            return self.evaluate(symbol, df, entry["strategy"], entry.get("params") or {}).score
        except ValueError:
            return -math.inf

    def run(self, symbol: str, df: pd.DataFrame, book: StrategyBook, promote: bool = True,
            strategies: list[str] | None = None) -> ImproveReport:
        inc = book.entry(symbol)
        board = self.search(symbol, df, strategies)
        if not board:
            return ImproveReport(symbol, inc, -math.inf, None, False, "no viable candidates", board)
        top = board[0]
        if top.strategy == inc["strategy"] and top.params == inc.get("params"):
            return ImproveReport(symbol, inc, -math.inf, top, False, "incumbent is already the best on train", board)
        best = self.evaluate(symbol, df, top.strategy, top.params)
        inc_score = self.incumbent_score(symbol, df, inc)
        ok, why = self.gate(best, inc_score)
        if ok and promote:
            book.promote(symbol, best.strategy, best.params,
                         {"holdout": best.test, "score": round(best.score, 3), "bars": len(df)}, source="walk-forward")
        board[0] = best
        return ImproveReport(symbol, inc, inc_score, best, ok and promote, why, board, passes=ok)
