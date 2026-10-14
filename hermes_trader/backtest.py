"""Vectorised backtester with fees, slippage and honest bar alignment.

Alignment: the engine evaluates a strategy at the close of bar t and trades
immediately, so the position held over bar t+1 equals target[t]. Costs are
charged on every change in position, in basis points of traded notional.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .strategies import Strategy

_TF_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def timeframe_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    unit = tf[-1]
    if unit not in _TF_SECONDS:
        raise ValueError(f"bad timeframe {tf!r}")
    return int(tf[:-1] or 1) * _TF_SECONDS[unit]


def periods_per_year(tf: str, asset_class: str = "crypto") -> float:
    secs = timeframe_seconds(tf)
    if asset_class == "equity":
        # ~252 sessions x 6.5h; daily+ bars count sessions
        if secs >= 86400:
            return 252 / (secs / 86400)
        return 252 * 6.5 * 3600 / secs
    return 365 * 86400 / secs


@dataclass
class BacktestResult:
    strategy: str
    params: dict[str, Any]
    bars: int
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    volatility: float
    trades: int
    win_rate: float
    profit_factor: float
    exposure: float
    fees_paid_pct: float
    equity: pd.Series = field(repr=False, default_factory=pd.Series)

    def summary(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("equity", None)
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}

    def score(self, min_trades: int = 0) -> float:
        """Single number the optimizer maximises: Sharpe, penalised for few trades and deep drawdowns."""
        if self.trades < min_trades or not math.isfinite(self.sharpe):
            return -math.inf
        return self.sharpe - 2.0 * max(0.0, self.max_drawdown - 0.20)


def _trade_returns(pos: np.ndarray, gross: np.ndarray, cost: np.ndarray) -> list[float]:
    out: list[float] = []
    cur = 1.0
    in_trade = False
    prev = 0.0
    for p, g, c in zip(pos, gross, cost, strict=True):
        if p != prev:  # position changed at start of this bar
            if in_trade:
                out.append(cur - 1.0)
            in_trade = p != 0
            cur = 1.0
        if in_trade:
            cur *= (1 + g) * (1 - c)
        prev = p
    if in_trade:
        out.append(cur - 1.0)
    return out


def backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    allow_short: bool = False,
    timeframe: str = "1h",
    asset_class: str = "crypto",
    size: float = 1.0,
    eval_from: int = 0,
) -> BacktestResult:
    """Run `strategy` over df. Indicators see all of df; metrics cover bars [eval_from:] only,
    which lets walk-forward tests warm up on training data without scoring it."""
    if len(df) < strategy.warmup() + 2:
        raise ValueError(f"need > {strategy.warmup() + 2} bars, got {len(df)}")
    close = df["close"].astype(float)
    tgt = strategy.targets(df).reindex(df.index).fillna(0.0).clip(-1, 1)
    if not allow_short:
        tgt = tgt.clip(lower=0)
    pos_all = (tgt.shift(1).fillna(0.0) * size).to_numpy()
    ret = close.pct_change().fillna(0.0).to_numpy()[eval_from:]
    pos = pos_all[eval_from:]
    prev0 = pos_all[eval_from - 1] if eval_from > 0 else 0.0
    turnover = np.abs(np.diff(np.concatenate([[prev0], pos])))
    cost_rate = (fee_bps + slippage_bps) / 1e4
    cost = turnover * cost_rate
    strat_ret = pos * ret
    net = (1 + strat_ret) * (1 - cost) - 1
    equity = pd.Series(np.cumprod(1 + net), index=df.index[eval_from:])

    ppy = periods_per_year(timeframe, asset_class)
    n = len(net)
    total = float(equity.iloc[-1] - 1)
    years = n / ppy
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else -1.0
    sd = float(np.std(net, ddof=1)) if n > 1 else 0.0
    mean = float(np.mean(net))
    sharpe = mean / sd * math.sqrt(ppy) if sd > 0 else 0.0
    downside = net[net < 0]
    dsd = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    sortino = mean / dsd * math.sqrt(ppy) if dsd > 0 else 0.0
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity.to_numpy()]))[1:]  # start from initial capital
    mdd = float(((peak - equity.to_numpy()) / peak).max())

    trades = _trade_returns(pos, strat_ret, cost)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else (math.inf if wins else 0.0)

    return BacktestResult(
        strategy=strategy.name,
        params=dict(strategy.params),
        bars=n,
        total_return=total,
        cagr=cagr,
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_drawdown=mdd,
        volatility=sd * math.sqrt(ppy),
        trades=len(trades),
        win_rate=len(wins) / len(trades) if trades else 0.0,
        profit_factor=float(pf),
        exposure=float(np.mean(np.abs(pos) > 0)),
        fees_paid_pct=float(cost.sum()),
        equity=equity,
    )


def buy_and_hold(df: pd.DataFrame, timeframe: str = "1h", asset_class: str = "crypto") -> dict[str, float]:
    eq = df["close"] / df["close"].iloc[0]
    peak = eq.cummax()  # eq starts at exactly 1.0
    r = eq.pct_change().dropna()
    ppy = periods_per_year(timeframe, asset_class)
    return {
        "total_return": round(float(eq.iloc[-1] - 1), 4),
        "sharpe": round(float(r.mean() / r.std() * math.sqrt(ppy)) if r.std() > 0 else 0.0, 4),
        "max_drawdown": round(float(((peak - eq) / peak).max()), 4),
    }
