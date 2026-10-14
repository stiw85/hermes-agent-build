---
name: drawdown-response
description: What to do when equity drawdown or a losing streak appears in the journal.
---

# Drawdown response

1. `journal_stats` → find which strategy/symbol drives the losses.
2. Compare live with that entry's promotion metrics in `strategy_book`:
   - Live losses within ~1.5x the backtest max drawdown → normal variance; change nothing and note it.
   - Clearly worse → `optimize(symbol)`; promote only via `promote_strategy`.
   - The last promotion made things worse → `rollback_strategy(symbol)`.
3. Record one specific lesson (symbol, strategy, regime, numbers).
4. Never try to win losses back by trading more; the risk limits are fixed for a reason.
