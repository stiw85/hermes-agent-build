"""Configuration: one YAML file + environment variables (secrets only live in env).

Precedence: built-in defaults < config.yaml < environment overrides.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "mode": "paper",  # paper | live
    "home": "./data",  # journal, state, memory, playbooks live here
    "broker": {
        "name": "paper",  # paper | ccxt | alpaca
        # paper broker
        "starting_cash": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "data_source": "synthetic",  # synthetic | csv | ccxt | alpaca
        "csv_dir": "./data/csv",
        # ccxt
        "exchange": "binance",
        "sandbox": True,
        # alpaca
        "paper": True,
        "crypto_feed": "us",
        "stock_feed": "iex",
    },
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "timeframe": "1h",
    "history_bars": 500,
    "allow_short": False,
    "default_strategy": {"name": "sma_cross", "params": {"fast": 20, "slow": 50}},
    "risk": {
        "max_position_pct": 0.20,  # of equity per symbol
        "max_gross_exposure_pct": 0.80,  # of equity across all symbols
        "max_order_notional": 2_500.0,  # hard cap per order, account currency
        "min_order_notional": 10.0,  # skip dust rebalances
        "risk_per_trade_pct": 0.01,  # ATR sizing: lose <=1% equity at stop
        "atr_stop_mult": 2.0,
        "max_daily_loss_pct": 0.03,  # halt new risk for the day
        "max_drawdown_pct": 0.15,  # kill switch: flatten + halt
        "rebalance_threshold": 0.10,  # ignore target changes smaller than this
        "max_trades_per_day": 20,
    },
    "llm": {
        "enabled": False,
        "provider": "auto",  # auto | openai (any /chat/completions endpoint) | anthropic (native Claude API)
        "base_url": "https://openrouter.ai/api/v1",  # any OpenAI-compatible endpoint
        "model": "nousresearch/hermes-4-70b",
        "api_key_env": "LLM_API_KEY",
        "temperature": 0.2,
        "timeout": 60,
        "max_tokens": 4096,  # anthropic only (required by its API)
        "trade_review": True,  # LLM may veto/shrink (never enlarge) proposed trades
        "on_review_error": "reduce",  # reduce (x0.5) | veto | proceed - when the LLM is down or replies garbage
        "max_tool_iterations": 12,
    },
    "jev": {
        "enabled": False,
        "mode": "shadow",  # shadow: score + journal only | gate: may shrink/veto new entries
        "url": "https://api.typesafe.ai/v1/systemone",  # or https://openrouter.ai/api/alpha/decisions
        "model": "jev-latest",  # OpenRouter: ~typesafe/jev-latest
        "api_key_env": "TYPESAFE_API_KEY",  # OpenRouter: OPENROUTER_API_KEY
        "timeout": 20,
        "veto_below": 0.40,  # gate: P(worth taking) below this -> skip the entry
        "reduce_below": 0.55,  # gate: below this -> half size
        "on_error": "proceed",  # gate mode when Jev is unreachable: proceed | reduce | veto
        "min_shadow_trades": 30,  # report won't suggest gating before this many scored trades have closed
        "checks": {  # every bar, every symbol: regime + strategy fit (+ exit check on open positions)
            "enabled": True,
            "mode": "shadow",  # shadow: record + score | act: may only block new entries or close positions
            "regime_block_below": 0.35,  # act: strategy stands aside (no new risk) when fit < this
            "exit_above": 0.70,  # act: close the position when P(exit) >= this
            "horizon_bars": 6,  # outcomes are scored this many bars later
            "min_resolved": 50,
        },
    },
    "improve": {
        "lookback_bars": 2000,
        "train_fraction": 0.7,
        "min_trades": 8,
        "min_improvement": 0.10,  # OOS score must beat incumbent by this (absolute Sharpe)
        "max_drawdown": 0.25,  # reject candidates with OOS DD above this
        "max_candidates": 60,
        "strategies": ["sma_cross", "ema_cross", "rsi_reversion", "donchian_breakout", "bollinger_reversion"],
        "reflect_after_trades": 10,
        "promote_cooldown_hours": 24,  # agent-requested promotions per symbol
    },
    "schedule": {
        "cycle_minutes": 60,
        "improve_every_hours": 24,
    },
    "notify": {
        "telegram_token_env": "TELEGRAM_BOT_TOKEN",
        "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
    },
}

LIVE_ACK_ENV = "HERMES_TRADER_LIVE"
LIVE_ACK_VALUE = "I_UNDERSTAND_REAL_MONEY"


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


DOTENV_FILES: list[str] = []  # which .env files were read (for error messages; never their contents)


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=VALUE lines; tolerates `export KEY=...`, spaces around `=`, quotes and trailing comments.
    Later non-empty values win over earlier ones (an empty placeholder never hides a real value)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if v[:1] in ("'", '"') and v.count(v[0]) >= 2:
            v = v[1 : v.index(v[0], 1)]
        elif " #" in v:
            v = v.split(" #", 1)[0].strip()
        if not k:
            continue
        if v or k not in out:
            out[k] = v
    return out


def load_dotenv(path: str | Path = ".env") -> None:
    """Load a .env file. A real (non-empty) value in the shell environment wins; an empty one doesn't."""
    p = Path(path).expanduser().resolve()
    if not p.is_file() or str(p) in DOTENV_FILES:
        return
    DOTENV_FILES.append(str(p))
    for k, v in parse_dotenv(p.read_text(errors="replace")).items():
        if v and not os.environ.get(k):
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)


def missing_secret_hint(name: str) -> str:
    where = ", ".join(DOTENV_FILES) or "no .env file found (looked in this folder and next to config.yaml)"
    return f"{name} is not set or empty. Read: {where}. Add a line like `{name}=your-key` (no quotes needed)."


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    path: Path | None = None

    # convenient accessors -------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def home(self) -> Path:
        h = Path(self.raw["home"]).expanduser()
        if not h.is_absolute() and self.path is not None:
            h = (self.path.parent / h).resolve()
        h.mkdir(parents=True, exist_ok=True)
        return h

    @property
    def is_live(self) -> bool:
        return self.raw.get("mode") == "live"

    def assert_live_allowed(self) -> None:
        if self.is_live and os.environ.get(LIVE_ACK_ENV) != LIVE_ACK_VALUE:
            raise RuntimeError(
                f"mode: live requires env {LIVE_ACK_ENV}={LIVE_ACK_VALUE}. "
                "Run in paper mode until the strategy has a track record."
            )

    def secret(self, env_name: str) -> str | None:
        return os.environ.get(env_name) or None


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    load_dotenv()  # ./.env
    raw = copy.deepcopy(DEFAULTS)
    cfg_path = None
    candidates = [path] if path else [os.environ.get("HERMES_TRADER_CONFIG"), "config.yaml"]
    for c in candidates:
        if c and Path(c).is_file():
            cfg_path = Path(c).resolve()
            load_dotenv(cfg_path.parent / ".env")  # .env next to config.yaml, wherever you run from
            raw = _deep_merge(raw, yaml.safe_load(cfg_path.read_text()) or {})
            break
    else:
        if path:
            raise FileNotFoundError(path)
    if overrides:
        raw = _deep_merge(raw, overrides)
    if os.environ.get("HERMES_TRADER_MODE"):
        raw["mode"] = os.environ["HERMES_TRADER_MODE"]
    if raw["mode"] not in ("paper", "live"):
        raise ValueError(f"mode must be paper or live, got {raw['mode']!r}")
    return Config(raw=raw, path=cfg_path)
