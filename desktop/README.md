# Hermes Trader Desktop

An Electron app for Hermes Trader, built on the stack and "deep-blue glass" design language of
[Herald OS](https://github.com/iamlukethedev/Herald-OS) (MIT): Electron 44, React 19, Tailwind 4 and ECharts.

| Page | What it does |
|---|---|
| **Overview** | Equity curve, today's P&L against the daily-loss limit, drawdown against the kill switch, positions, recent activity. Start/stop the bot, run one cycle, halt/resume, flatten all. |
| **Markets** | Candles with SMA 50/200 and the bot's own buy and sell fills; volatility, RSI, ATR and trend; the strategy each symbol trades; recent decisions. |
| **Strategies** | The versioned strategy book (with roll-back), walk-forward search with the holdout gate (promote only if it passes), and a backtest lab compared with buy-and-hold. |
| **Journal** | Live P&L by strategy, plus every trade, decision (including the LLM verdict) and event. |
| **Brain** | Learned lessons, playbooks, and chat with the agent (needs `llm.enabled`). |
| **Settings** | Backend connection, read-only trading config and risk limits, backend log. |

## Run it (Linux)

```bash
# 1. the bot (once): see the main README
cd ~/hermes-trader && source .venv/bin/activate && hermes-trader init

# 2. the app
cd ~/hermes-trader/desktop
npm install            # needs Node 22.12+
npm start              # builds, then opens the app
```

On first launch the app looks for `config.yaml` in `~/hermes-trader`. If yours is somewhere else, change the folder in **Settings**.

To get an installable build, run `npm run dist:linux`. It writes an AppImage and a `.tar.gz` to `release/`.

## Two ways to connect

- **Start it for me** (default): the app runs `hermes-trader serve` in your project folder. The bot only trades while the app is open. Quitting asks first if the bot is running, lets any cycle in progress finish, then stops it. If the app crashes, the backend notices (its stdin closes), finishes its cycle and exits, so it never keeps trading unattended.
- **Attach to a running one** (for 24/7 trading): run `hermes-trader serve --run` in tmux or systemd yourself. The app connects to `http://127.0.0.1:8765` using the token in `data/api_token`. Closing the app leaves your bot running.

## Safety model

- The API listens on `127.0.0.1` only. It rejects foreign `Host` headers (which blocks DNS rebinding) and requires a random bearer token for every call. The token stays in the Electron main process and never reaches the web page.
- Before sending the token, the app makes the server prove it knows it (an HMAC challenge), so another program sitting on the port can't capture it.
- The page can only call an allowlist of endpoints. Changing the command, folder, URL or token file the app trusts needs a native confirmation dialog.
- Risk limits are read-only in the app, and there is no manual-order button.
- Actions that move money ask first:
  - **Start bot** and **Run cycle now** need a confirmation. In live mode you also type `LIVE`.
  - **Flatten** needs you to type `FLATTEN`, and the server checks that too.
  - **Halt** asks for a reason, which goes in the journal.
- A paper/live badge stays in the title bar at all times.

## Development

```bash
npm run dev         # Vite dev server + Electron with live reload
npm run typecheck
npm test            # vitest (IPC allowlist, command resolution)
```

The chart palette (`--color-series-1/2`) was checked against the dark glass surface for colour-blind separation, lightness and contrast. Profit and loss colours (mint/red) are only used for direction.
