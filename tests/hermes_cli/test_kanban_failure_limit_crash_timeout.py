"""The dispatcher's ``failure_limit`` (``kanban.failure_limit``) governs every
non-success path of a tick, crashes and max-runtime timeouts included."""

from __future__ import annotations

import subprocess
import sys
import time
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


def _dead_pid(code: int = 3) -> int:
    proc = subprocess.Popen([sys.executable, "-c", f"import sys; sys.exit({code})"])
    proc.wait()
    return proc.pid


def _gave_up(conn, tid):
    return [e.payload for e in kb.list_events(conn, tid) if e.kind == "gave_up"]


def test_crash_blocks_at_the_dispatcher_failure_limit(kanban_home, all_assignees_spawnable, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="crasher", assignee="worker")
        kbd.dispatch_once(conn, spawn_fn=lambda task, ws: _dead_pid(), failure_limit=1)
        res = kbd.dispatch_once(conn, spawn_fn=lambda task, ws: _dead_pid(), failure_limit=1)

        task = kb.get_task(conn, tid)
        assert res.crashed == [tid]
        assert task.status == "blocked"
        assert task.consecutive_failures == 1
        assert [p["effective_limit"] for p in _gave_up(conn, tid)] == [1]


def test_crash_below_a_raised_failure_limit_does_not_give_up(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="crasher", assignee="worker")
        blocked = []
        for _ in range(4):  # spawn, then three crash+respawn ticks
            res = kbd.dispatch_once(conn, spawn_fn=lambda task, ws: _dead_pid(), failure_limit=4)
            blocked.extend(res.auto_blocked)

        assert kb.get_task(conn, tid).consecutive_failures == 3
        assert blocked == []
        assert _gave_up(conn, tid) == []


def test_max_runtime_timeout_blocks_at_the_dispatcher_failure_limit(kanban_home, monkeypatch):
    # Inside the crash launch-window grace, so the dead PID reaches the
    # max-runtime sweep instead of being booked as a crash.
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "600")
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="overrun", assignee="worker", max_runtime_seconds=1)
        kb.claim_task(conn, tid)
        kbd._set_worker_pid(conn, tid, _dead_pid())
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE task_runs SET started_at = ? "
                "WHERE id = (SELECT current_run_id FROM tasks WHERE id = ?)",
                (int(time.time()) - 30, tid),
            )

        res = kbd.dispatch_once(conn, spawn_fn=lambda task, ws: None, failure_limit=1, max_spawn=0)

        assert res.timed_out == [tid]
        assert kb.get_task(conn, tid).status == "blocked"
        assert [p["effective_limit"] for p in _gave_up(conn, tid)] == [1]
