"""An operator ``promote`` out of an explicit block ends that block: a later
plain circuit-breaker trip is judged by the failure counter again."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_breaker_trip_after_manual_promote_is_released_by_reassign(kanban_home):
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="t", assignee="dev")
        kb.claim_task(conn, tid)
        assert kb.block_task(conn, tid, reason="need input")
        assert kb.promote_task(conn, tid, actor="operator") == (True, None)

        for _ in range(2):
            kbd._record_task_failure(conn, tid, "boom", outcome="crashed", failure_limit=2)
        assert kb.get_task(conn, tid).status == "blocked"
        assert kb.recompute_ready(conn, failure_limit=2) == 0  # at the limit: held

        kb.assign_task(conn, tid, "other")  # fresh profile, fresh budget
        assert kb.recompute_ready(conn, failure_limit=2) == 1
        assert kb.get_task(conn, tid).status == "ready"
