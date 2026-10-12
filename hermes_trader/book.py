"""Strategy book: which strategy + params each symbol currently trades, with version history.

Lives in <home>/strategy_book.yaml so you can read and hand-edit it. Every promotion
appends to history, so `hermes-trader rollback SYMBOL` can undo a bad change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import utcnow
from .strategies import Strategy, make


class StrategyBook:
    def __init__(self, path: str | Path, default: dict[str, Any]) -> None:
        self.path = Path(path)
        self.default = default
        self.data: dict[str, Any] = {}
        if self.path.is_file():
            self.data = yaml.safe_load(self.path.read_text()) or {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(self.data, sort_keys=False))
        tmp.replace(self.path)

    def entry(self, symbol: str) -> dict[str, Any]:
        e = self.data.get(symbol)
        if e:
            return e
        return {"strategy": self.default["name"], "params": dict(self.default.get("params") or {}),
                "version": 0, "source": "default"}

    def strategy_for(self, symbol: str) -> Strategy:
        e = self.entry(symbol)
        return make(e["strategy"], e.get("params"))

    def promote(self, symbol: str, strategy: str, params: dict[str, Any], metrics: dict[str, Any],
                source: str) -> dict[str, Any]:
        make(strategy, params)  # validate before writing
        old = self.data.get(symbol)
        hist = list(old.get("history", [])) if old else []
        if old:
            hist.append({k: old[k] for k in ("strategy", "params", "version", "promoted_at", "metrics", "source")
                         if k in old})
        new = {
            "strategy": strategy,
            "params": params,
            "version": (old or {}).get("version", 0) + 1,
            "promoted_at": utcnow().isoformat(),
            "source": source,
            "metrics": metrics,
            "history": hist[-10:],
        }
        self.data[symbol] = new
        self.save()
        return new

    def rollback(self, symbol: str) -> dict[str, Any] | None:
        cur = self.data.get(symbol)
        if not cur or not cur.get("history"):
            return None
        prev = cur["history"][-1]
        self.data[symbol] = {**prev, "version": cur["version"] + 1, "source": f"rollback of v{cur['version']}",
                             "promoted_at": utcnow().isoformat(), "history": cur["history"][:-1]}
        self.save()
        return self.data[symbol]

    def summary(self) -> dict[str, Any]:
        return {s: {k: v for k, v in e.items() if k != "history"} for s, e in self.data.items()}
