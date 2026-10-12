# Hermes Trader ☤📈

A lean, self-improving trading agent distilled from [Nous Research's Hermes Agent](https://github.com/NousResearch/hermes-agent).

The original Hermes is a general-purpose assistant: about 18,000 files and 247 MB, with chat gateways, desktop apps, browser automation, TTS, a website and 35 locales. This branch keeps only the ideas that matter for trading and rebuilds them as **~2,900 lines of Python with 4 core dependencies**:

| Kept from Hermes | Became |
|---|---|
| Model-agnostic LLM loop with tool calling | `agent/llm.py`, `agent/loop.py` (any OpenAI-compatible endpoint: OpenRouter, Nous Portal, OpenAI, Ollama, vLLM…) |
| `MEMORY.md` curated memory | `LESSONS.md`: short, falsifiable trading lessons with a character budget |
| Skills (procedural memory, agentskills.io format) | `hermes_trader/playbooks/*/SKILL.md`: regime checks, drawdown response, onboarding. The agent can write its own. |
| Background self-review after work | `reflect`: reviews the trade journal, records lessons, re-optimises underperformers |
| Cron scheduler | Bar-close scheduler (`run`) plus daily walk-forward re-optimisation |
| `SOUL.md` persona | Trading persona: sceptical, capital-preservation first |
| Telegram gateway | One function: Telegram trade and alert notifications |

## Architecture

```
            ┌──────────── every bar close ─────────────┐
 broker ──► data ──► strategy ──► ATR stop ──► RISK ──► (LLM review: shrink/veto only) ──► execute ──► journal
 (paper │ ccxt │ alpaca)     ▲                  hard limits                                         │
                             │                                                                     ▼
                     strategy_book.yaml ◄── walk-forward optimizer (daily) ◄── reflection (every N trades)
                     (versioned, rollback)         gates: OOS score, trades, DD       writes LESSONS.md + playbooks
```

**Safety design**
- The bot trades **without** an LLM. The LLM is an optional overlay that can only *shrink or veto* new risk. It can never enlarge an order or block an exit. If the LLM is down, the bot proceeds on strategy + risk alone and logs it.
- Risk limits live only in `config.yaml`. The agent has no tool to change them.
- Strategy changes go through a **walk-forward gate**: the optimiser tunes on the first 70% of history, scores on the unseen last 30%, and promotes only if the challenger beats the incumbent's out-of-sample score by a margin, with enough trades and acceptable drawdown. This applies to the LLM's requests too.
- Circuit breakers: a daily loss limit switches to reduce-only, and a max-drawdown **kill switch** flattens everything and halts until you run `resume`.
- Paper mode is the default. A paper config pointed at a real exchange is refused. `mode: live` also needs the env latch `HERMES_TRADER_LIVE=I_UNDERSTAND_REAL_MONEY`.

## Quick start

```bash
pip install -e ".[crypto]"         # ccxt for crypto exchanges; Alpaca needs nothing extra
hermes-trader init                  # creates config.yaml + .env
hermes-trader backtest BTC/USDT     # offline synthetic data by default
hermes-trader optimize --promote    # walk-forward search across all strategies
hermes-trader run --once            # one trading cycle (cron-friendly)
hermes-trader run                   # loop on every bar close
hermes-trader status                # equity, positions, risk state
```

### Pick a market (edit `config.yaml`)

**Crypto paper trading on real prices (no keys needed):**
```yaml
broker: {name: paper, data_source: ccxt, exchange: binance}
symbols: [BTC/USDT, ETH/USDT, SOL/USDT]
```

**Crypto on an exchange testnet** (put `BINANCE_API_KEY`/`BINANCE_SECRET` testnet keys in `.env`):
```yaml
broker: {name: ccxt, exchange: binance, sandbox: true}
```

**US stocks and ETFs with Alpaca's free paper account** (put `ALPACA_API_KEY_ID`/`ALPACA_API_SECRET_KEY` in `.env`):
```yaml
broker: {name: alpaca}
symbols: [SPY, QQQ, AAPL]          # crypto on Alpaca: BTC/USD
timeframe: 1h
```
Equity symbols are skipped automatically while the market is closed.

### Turn on the LLM brain (optional)
```yaml
llm:
  enabled: true
  base_url: https://openrouter.ai/api/v1      # or http://localhost:11434/v1 (Ollama, free, local)
  model: nousresearch/hermes-4-70b
```
Set `LLM_API_KEY` in `.env`, then:
```bash
hermes-trader chat "how is ETH doing and is the current strategy still right for it?"
hermes-trader reflect               # force a self-review now
hermes-trader lessons               # what it has learned
```
In `chat`, the agent can also place manual orders. Every one needs you to type `yes`, and the risk caps still apply.

## Commands

| Command | What it does |
|---|---|
| `init` | Create `config.yaml` and `.env` from the examples |
| `backtest SYMBOL [--strategy S --params JSON --bars N]` | Backtest with fees and slippage, compared with buy-and-hold |
| `optimize [SYMBOL] [--promote]` | Walk-forward search; promotes only gate-passing winners |
| `run [--once]` | Trade on bar close; re-optimises daily, reflects every N closed trades |
| `status` / `journal` / `book` / `lessons` | Inspect state, live P&L, active strategies, memory |
| `flatten` / `halt` / `resume` | Emergency controls |
| `rollback SYMBOL` | Revert to the previous strategy version |
| `chat` / `reflect` | Talk to the agent / run a self-review |
| `download SYMBOL --bars N` | Save history to CSV (`data_source: csv`) |

## Strategies

`sma_cross`, `ema_cross`, `donchian_breakout` (trend); `rsi_reversion`, `bollinger_reversion`, `trend_rsi` (mean reversion). To add your own, subclass `Strategy`, implement `targets(df)` returning exposure in [-1, 1], and `register()` it. The no-look-ahead test runs automatically over every registered strategy.

## Layout

```
hermes_trader/
  config.py  models.py  indicators.py  backtest.py  data.py
  risk.py  engine.py  journal.py  book.py  improve.py  runtime.py  cli.py
  brokers/   base.py  paper.py  ccxt_broker.py  alpaca_broker.py
  strategies/ base.py  builtin.py
  agent/     llm.py  loop.py  tools.py  memory.py  prompts.py
  playbooks/ bundled procedural playbooks (SKILL.md)
  templates/ config.example.yaml, env.example (copied by `init`)
tests/       48 tests: no-look-ahead, risk limits, kill switch, broker adapters, LLM veto/clamp, gated promotion
```

Runtime state lives in `data/` (`journal.sqlite`, `strategy_book.yaml`, `LESSONS.md`, `playbooks/`, broker state). Back it up, because this is what the bot has learned.

## Docker
```bash
docker build -t hermes-trader .
docker run -d --name trader --env-file .env -v $PWD/config.yaml:/app/config.yaml -v $PWD/data:/app/data hermes-trader
```

## Honest caveats
- Backtests on synthetic data only prove that the plumbing works. Use real history (`data_source: ccxt` or `alpaca`, or CSV) before trusting any strategy.
- Walk-forward gating reduces overfitting; it does not eliminate it. Paper trade for weeks before considering `mode: live`.
- Spot or cash only. There is no leverage, margin or derivatives support, by design.
- This is not financial advice. You are responsible for any orders it places.

## License
MIT. Derived from Hermes Agent © Nous Research (see `LICENSE` and `NOTICE`).
