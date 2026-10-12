"""Storage for native learning memory: conclusions with premises, FTS5 recall, supersession.

The store is a SQLite file the provider owns (``$HERMES_HOME/memory_native.db``), not a table in the
core state DB: the core DB carries its own lock, repair and migration machinery, and a provider that
lives in its own file can be removed or reset without touching session history.

Nothing is deleted silently. A contradicted conclusion gets ``superseded_by`` set and stays readable
through :meth:`NativeStore.get`; only an explicit :meth:`NativeStore.forget` removes a row.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

KIND_FACT = "fact"
KIND_OUTCOME = "outcome"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conclusions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id TEXT NOT NULL DEFAULT 'user',
    kind TEXT NOT NULL DEFAULT 'fact',
    text TEXT NOT NULL,
    premises_json TEXT NOT NULL DEFAULT '[]',
    source_session_id TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    task_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    corrected INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    superseded_by INTEGER REFERENCES conclusions(id)
);
CREATE INDEX IF NOT EXISTS conclusions_peer_kind ON conclusions(peer_id, kind, superseded_by);
CREATE VIRTUAL TABLE IF NOT EXISTS conclusions_fts USING fts5(text, content='conclusions', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS conclusions_ai AFTER INSERT ON conclusions BEGIN
    INSERT INTO conclusions_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS conclusions_ad AFTER DELETE ON conclusions BEGIN
    INSERT INTO conclusions_fts(conclusions_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS conclusions_au AFTER UPDATE OF text ON conclusions BEGIN
    INSERT INTO conclusions_fts(conclusions_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO conclusions_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS learned_sessions (
    session_id TEXT PRIMARY KEY,
    learned_at REAL NOT NULL,
    added INTEGER NOT NULL DEFAULT 0
);
"""

_TOKEN_RE = re.compile(r"[\w']+")
_MAX_QUERY_TERMS = 24
_MAX_DUPLICATE_SCAN = 2000


def normalize(text: str) -> str:
    """Case, punctuation and whitespace folded: the key used for exact-duplicate checks."""
    return " ".join(_TOKEN_RE.findall((text or "").lower()))


# Words that appear in almost every conclusion ("user", "has") or in almost every query. Left in, they
# OR-match unrelated rows, so they are dropped before the MATCH expression is built.
_STOPWORDS = frozenset({
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "to",
    "too",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "user",
    "users",
    "about",
    "also",
    "just",
    "like",
})


def fts_query(text: str) -> str:
    """An FTS5 MATCH expression that ORs the distinct, non-stopword terms of ``text``, quoted so no input is syntax."""
    terms: list[str] = []
    for token in _TOKEN_RE.findall((text or "").lower()):
        token = token.strip("'")
        if len(token) < 2 or token in terms or token in _STOPWORDS:
            continue
        terms.append(token)
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    return " OR ".join(f'"{term}"' for term in terms)


class NativeStore:
    """Thread-safe SQLite access. Every public method takes the lock, so the learning thread and the
    turn loop can share one connection."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- writes -------------------------------------------------------------

    def add(
        self,
        *,
        text: str,
        peer_id: str = "user",
        kind: str = KIND_FACT,
        premises: Iterable[str] = (),
        session_id: str = "",
        confidence: float = 0.5,
        task_type: str = "",
        status: str = "",
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conclusions (peer_id, kind, text, premises_json, source_session_id, confidence,"
                " task_type, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    peer_id,
                    kind,
                    text,
                    json.dumps(list(premises)),
                    session_id,
                    float(confidence),
                    task_type,
                    status,
                    time.time(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def supersede(self, old_id: int, new_id: int, *, peer_id: str = "user") -> bool:
        """Mark ``old_id`` as replaced by ``new_id``. Only an active row of the same peer can be superseded."""
        if old_id == new_id:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE conclusions SET superseded_by = ? WHERE id = ? AND peer_id = ? AND superseded_by IS NULL",
                (new_id, old_id, peer_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def correct(self, row_id: int, text: str) -> bool:
        """Replace a conclusion's text (a user correction). Premises are kept so the history stays explainable."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE conclusions SET text = ?, corrected = 1 WHERE id = ?",
                (text, row_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def forget(self, row_id: int) -> bool:
        """Explicit user removal. The only operation that deletes a conclusion."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM conclusions WHERE id = ?", (row_id,))
            self._conn.commit()
            return cur.rowcount == 1

    def save_summary(self, session_id: str, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO session_summaries (session_id, summary, created_at) VALUES (?, ?, ?)",
                (session_id, summary, time.time()),
            )
            self._conn.commit()

    def mark_learned(self, session_id: str, added: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO learned_sessions (session_id, learned_at, added) VALUES (?, ?, ?)",
                (session_id, time.time(), int(added)),
            )
            self._conn.commit()

    # -- reads --------------------------------------------------------------

    def is_learned(self, session_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM learned_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None

    def get(self, row_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM conclusions WHERE id = ?", (row_id,)
            ).fetchone()
        return _as_dict(row) if row else None

    def find_duplicate(self, text: str, *, peer_id: str, kind: str) -> Optional[int]:
        """Id of an active row whose normalised text equals ``text``'s, or None."""
        key = normalize(text)
        for row in self.active(peer_id=peer_id, kind=kind, limit=_MAX_DUPLICATE_SCAN):
            if normalize(row["text"]) == key:
                return int(row["id"])
        return None

    def active(
        self, *, peer_id: str = "user", kind: str = KIND_FACT, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Newest active (not superseded) rows of one kind."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conclusions WHERE peer_id = ? AND kind = ? AND superseded_by IS NULL"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (peer_id, kind, int(limit)),
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def every_row(self, *, peer_id: str = "user") -> list[dict[str, Any]]:
        """Every conclusion of one peer, active or superseded, oldest first. For export only."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conclusions WHERE peer_id = ? ORDER BY id", (peer_id,)
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def search(
        self, query: str, *, peer_id: str = "user", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Active fact rows matching any term of ``query``, best BM25 first, each with a ``rank`` field."""
        match = fts_query(query)
        if not match:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, bm25(conclusions_fts) AS rank FROM conclusions_fts"
                " JOIN conclusions c ON c.id = conclusions_fts.rowid"
                " WHERE conclusions_fts MATCH ? AND c.peer_id = ? AND c.kind = ? AND c.superseded_by IS NULL"
                " ORDER BY rank LIMIT ?",
                (match, peer_id, KIND_FACT, int(limit)),
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def outcomes(
        self, task_type: str, *, peer_id: str = "user", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Task outcome records for one task type, newest first. Curator input; never part of recall."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conclusions WHERE peer_id = ? AND kind = ? AND task_type = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (peer_id, KIND_OUTCOME, task_type, int(limit)),
            ).fetchall()
        return [_as_dict(r) for r in rows]


def _as_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["premises"] = json.loads(data.pop("premises_json") or "[]")
    return data
