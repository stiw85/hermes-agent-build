---
name: new-symbol-onboarding
description: Steps before trading a newly added symbol.
---

# New symbol onboarding

1. `market_snapshot` → check that data looks sane (bars present, no zero prices, plausible volatility).
2. `optimize(symbol)` → review the leaderboard; prefer simple strategies with more trades over a single lucky outlier.
3. `run_backtest` for the top candidate and compare with buy-and-hold.
4. `promote_strategy` only if it passes the gate; otherwise leave the default and let the scheduled optimizer revisit.
5. Add a lesson with the symbol's typical `vol_annual` and `atr_pct` for future regime checks.
