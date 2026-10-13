"""SQLite trade journal: every decision, fill, equity snapshot and event.

This is the bot's ground truth for self-review: the reflection loop reads it,
never the other way round.
"""

from __future__ import annotations

import json
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS jev_scores (
  id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, side TEXT, strategy TEXT, p REAL, regime TEXT,
  regime_conf REAL, verdict TEXT, mode TEXT, applied INTEGER, cost REAL, model TEXT, error TEXT,
  taken INTEGER DEFAULT 0, order_id TEXT, outcome_pnl REAL, closed_ts TEXT
);
CREATE TABLE IF NOT EXISTS jev_checks (
  id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, kind TEXT, strategy TEXT, regime TEXT, regime_conf REAL,
  p REAL, side_sign INTEGER, price REAL, mode TEXT, applied INTEGER DEFAULT 0, cost REAL, model TEXT,
  error TEXT, fwd_ret REAL, resolved_ts TEXT
);
CREATE TABLE IF NOT EXISTS filter_checks (
  id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, strategy TEXT, name TEXT, side_sign INTEGER, price REAL,
  passed INTEGER, applied INTEGER DEFAULT 0, mode TEXT, value REAL, note TEXT, error TEXT,
  fwd_ret REAL, resolved_ts TEXT
);
CREATE INDEX IF NOT EXISTS ix_filter_open ON filter_checks(symbol, resolved_ts, ts);
CREATE INDEX IF NOT EXISTS ix_fills_symbol ON fills(symbol);
CREATE INDEX IF NOT EXISTS ix_jev_checks_open ON jev_checks(symbol, resolved_ts, ts);
CREATE INDEX IF NOT EXISTS ix_jev_open ON jev_scores(symbol, taken, closed_ts);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind);
"""


class Journal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # one connection shared by the bot thread and API threads
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a journal was created (old journals keep working)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(decisions)")}
        for name, typ in (("jev_p", "REAL"), ("jev_note", "TEXT")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE decisions ADD COLUMN {name} {typ}")
        self.db.commit()

    def _ins(self, table: str, row: dict[str, Any]) -> int:
        row = {"ts": utcnow().isoformat(), **row}
        cols = ",".join(row)
        q = ",".join("?" for _ in row)
        with self.lock:
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
        with self.lock:
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
        return int(self.rows("SELECT COUNT(*) AS n FROM fills WHERE realized_pnl IS NOT NULL")[0]["n"])

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
            "fills": int(self.rows("SELECT COUNT(*) AS n FROM fills WHERE status='filled'")[0]["n"]),
            "closed_trades": self.closed_trade_count(),
            "realized_pnl": round(sum(r["pnl"] or 0 for r in by), 2),
            "by_strategy_symbol": by,
            "equity_first": curve[0] if curve else None,
            "equity_last": curve[-1] if curve else None,
            "max_drawdown": round(mdd, 4),
        }

    # ---- JEV scores ------------------------------------------------------
    def jev_score(self, **row: Any) -> int:
        return self._ins("jev_scores", row)

    def jev_mark_taken(self, score_id: int, order_id: str) -> None:
        with self.lock:
            self.db.execute("UPDATE jev_scores SET taken=1, order_id=? WHERE id=?", (order_id, score_id))
            self.db.commit()

    def jev_add_pnl(self, symbol: str, pnl: float) -> None:
        """Realised P&L of a closing fill counts toward every still-open scored entry on that symbol."""
        with self.lock:
            self.db.execute("UPDATE jev_scores SET outcome_pnl = COALESCE(outcome_pnl, 0) + ? "
                            "WHERE symbol=? AND taken=1 AND closed_ts IS NULL", (pnl, symbol))
            self.db.commit()

    def jev_close(self, symbol: str) -> None:
        with self.lock:
            self.db.execute("UPDATE jev_scores SET closed_ts=?, outcome_pnl=COALESCE(outcome_pnl, 0) "
                            "WHERE symbol=? AND taken=1 AND closed_ts IS NULL", (utcnow().isoformat(), symbol))
            self.db.commit()

    def jev_check(self, **row: Any) -> int:
        return self._ins("jev_checks", row)

    def jev_check_resolve(self, symbol: str, cutoff_ts: str, price: float, now_ts: str) -> int:
        """Score checks made at or before `cutoff_ts`: forward return in their direction up to `price`."""
        return self._resolve("jev_checks", symbol, cutoff_ts, price, now_ts)

    def _resolve(self, table: str, symbol: str, cutoff_ts: str, price: float, now_ts: str) -> int:
        assert table in ("jev_checks", "filter_checks")
        with self.lock:
            due = self.db.execute(
                f"SELECT id, price, side_sign FROM {table} WHERE symbol=? AND resolved_ts IS NULL "
                "AND error IS NULL AND ts <= ?", (symbol, cutoff_ts)).fetchall()
            for r in due:
                fwd = (r["side_sign"] or 0) * (price / r["price"] - 1) if r["price"] else None
                self.db.execute(f"UPDATE {table} SET fwd_ret=?, resolved_ts=? WHERE id=?", (fwd, now_ts, r["id"]))
            self.db.commit()
            return len(due)

    # ---- entry filters -------------------------------------------------------------------
    def filter_check(self, **row: Any) -> int:
        return self._ins("filter_checks", row)

    def filter_resolve(self, symbol: str, cutoff_ts: str, price: float, now_ts: str) -> int:
        return self._resolve("filter_checks", symbol, cutoff_ts, price, now_ts)

    def filter_rows(self, n: int = 20000) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM filter_checks ORDER BY id DESC LIMIT ?", (n,))

    def jev_check_rows(self, n: int = 20000) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM jev_checks ORDER BY id DESC LIMIT ?", (n,))

    def jev_latest_check(self, symbol: str) -> dict[str, Any] | None:
        rows = self.rows("SELECT * FROM jev_checks WHERE symbol=? AND kind='regime' ORDER BY id DESC LIMIT 1",
                         (symbol,))
        return rows[0] if rows else None

    def jev_rows(self, n: int = 5000) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM jev_scores ORDER BY id DESC LIMIT ?", (n,))

    def close(self) -> None:
        self.db.close()
