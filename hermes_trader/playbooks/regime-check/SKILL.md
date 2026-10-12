---
name: regime-check
description: Classify a symbol's market regime (trend/range/high-vol) before trusting a strategy signal.
---

# Regime check

1. `market_snapshot(symbol)`.
2. Classify:
   - **Trend**: `trend_sma50_200` is up/down AND |chg_100| > 2 x atr_pct x 10.
   - **Range**: trend "mixed" and price inside the middle 60% of `range_100`.
   - **High-vol**: `vol_annual` > 1.5x its usual level for this symbol (check lessons), or atr_pct spikes.
3. Fit:
   - Trend: favour sma_cross / ema_cross / donchian_breakout. Be wary of mean-reversion entries against the trend.
   - Range: favour rsi_reversion / bollinger_reversion / trend_rsi.
   - High-vol: in trade review prefer `reduce` (size_mult 0.5) over full size.
4. If the active strategy doesn't fit the regime for several days, run `optimize(symbol)` rather than overriding by hand.
