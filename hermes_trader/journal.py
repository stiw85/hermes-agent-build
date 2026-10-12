"""SQLite trade journal: every decision, fill, equity snapshot and event.

This is the bot's ground truth for self-review: the reflection loop reads it,
never the other way round.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, strategy TEXT, params TEXT,
  target REAL, price REAL, signal_reason TEXT, risk_notes TEXT,
  llm_verdict TEXT, llm_note TEXT, action TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY, ts TEXT, order_id TEXT, symbol TEXT, side TEXT, qty REAL,
  price REAL, fee REAL, status TEXT, strategy TEXT, reason TEXT, realized_pnl REAL
);
CREATE TABLE IF NOT EXISTS equity (ts TEXT, equity REAL, cash REAL, gross_exposure REAL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, message TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ix_fills_symbol ON fills(symbol);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind);
"""


class Journal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _ins(self, table: str, row: dict[str, Any]) -> int:
        row = {"ts": utcnow().isoformat(), **row}
        cols = ",".join(row)
        q = ",".join("?" for _ in row)
        cur = self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", list(row.values()))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def decision(self, **row: Any) -> int:
        if isinstance(row.get("params"), dict):
            row["params"] = json.dumps(row["params"])
        if isinstance(row.get("risk_notes"), list):
            row["risk_notes"] = "; ".join(row["risk_notes"])
        return self._ins("decisions", row)

    def fill(self, **row: Any) -> int:
        return self._ins("fills", row)

    def equity(self, equity: float, cash: float, gross: float) -> None:
        self._ins("equity", {"equity": equity, "cash": cash, "gross_exposure": gross})

    def event(self, kind: str, message: str, data: Any = None) -> None:
        self._ins("events", {"kind": kind, "message": message, "data": json.dumps(data, default=str) if data else None})

    # ---- queries ------------------------------------------------------
    def rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def recent_fills(self, n: int = 50) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM fills WHERE status='filled' ORDER BY id DESC LIMIT ?", (n,))

    def recent_decisions(self, n: int = 50) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (n,))

    def recent_events(self, n: int = 30, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self.rows("SELECT * FROM events WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, n))
        return self.rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,))

    def closed_trade_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM fills WHERE realized_pnl IS NOT NULL").fetchone()[0])

    def stats(self) -> dict[str, Any]:
        by = self.rows(
            """SELECT strategy, symbol, COUNT(*) AS closes, ROUND(SUM(realized_pnl), 2) AS pnl,
                      SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                      ROUND(SUM(fee), 2) AS fees
               FROM fills WHERE realized_pnl IS NOT NULL GROUP BY strategy, symbol ORDER BY pnl"""
        )
        for r in by:
            r["win_rate"] = round(r["wins"] / r["closes"], 3) if r["closes"] else 0.0
        eq = self.rows("SELECT equity FROM equity ORDER BY rowid")
        curve = [r["equity"] for r in eq]
        peak, mdd = 0.0, 0.0
        for v in curve:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak if peak else 0.0)
        return {
            "fills": int(self.db.execute("SELECT COUNT(*) FROM fills WHERE status='filled'").fetchone()[0]),
            "closed_trades": self.closed_trade_count(),
            "realized_pnl": round(sum(r["pnl"] or 0 for r in by), 2),
            "by_strategy_symbol": by,
            "equity_first": curve[0] if curve else None,
            "equity_last": curve[-1] if curve else None,
            "max_drawdown": round(mdd, 4),
        }

    def close(self) -> None:
        self.db.close()
