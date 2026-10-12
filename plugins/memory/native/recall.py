"""Per-turn recall for native learning memory: FTS candidates, recency weighting, a bounded block.

No LLM call happens here. The turn pays for one local SQLite query, and the block it returns is
capped by characters, so recall cannot grow the prompt without limit.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional

from .store import NativeStore

DEFAULT_LIMIT = 5
DEFAULT_CHAR_BUDGET = 1200
CANDIDATE_POOL = 50
# A fact's weight halves every six months, so a conclusion from last year needs a much better textual
# match than one from last week to outrank it.
HALF_LIFE_DAYS = 180.0

HEADING = "Things you have learned about the user from earlier sessions (may be out of date; trust the current conversation over these):"


def score(row: dict, *, now: Optional[float] = None) -> float:
    """Higher is better. ``rank`` is SQLite's BM25 (more negative is a better match)."""
    current = time.time() if now is None else now
    age_days = max(0.0, (current - float(row.get("created_at") or current)) / 86400.0)
    relevance = -float(row.get("rank") or 0.0)
    return relevance * (0.5 ** (age_days / HALF_LIFE_DAYS))


def select(
    rows: Iterable[dict], *, limit: int = DEFAULT_LIMIT, now: Optional[float] = None
) -> list[dict]:
    ranked = sorted(rows, key=lambda r: score(r, now=now), reverse=True)
    return ranked[:limit]


def recall_block(
    store: NativeStore,
    query: str,
    *,
    peer_id: str = "user",
    limit: int = DEFAULT_LIMIT,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    now: Optional[float] = None,
) -> tuple[str, list[int]]:
    """The recall block for ``query`` and the ids it contains. ``("", [])`` when nothing matches."""
    candidates = store.search(query, peer_id=peer_id, limit=CANDIDATE_POOL)
    chosen = select(candidates, limit=limit, now=now)
    lines: list[str] = []
    ids: list[int] = []
    used = len(HEADING) + 1
    for row in chosen:
        line = f"- {' '.join(str(row['text']).split())}"
        if used + len(line) + 1 > char_budget:
            break
        lines.append(line)
        ids.append(int(row["id"]))
        used += len(line) + 1
    if not lines:
        return "", []
    return HEADING + "\n" + "\n".join(lines), ids
