"""``kanban.default_assignee`` lands on the task row in canonical (lowercase)
form, like every other assignee write, so it is one profile to the board."""

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
    profile = home / "profiles" / "coder"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("{}\n", encoding="utf-8")
    kb.init_db()
    return home


def test_mixed_case_default_assignee_is_stored_canonical(kanban_home):
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="unassigned")
        res = kbd.dispatch_once(conn, spawn_fn=lambda task, ws: None, default_assignee="Coder")

        assert res.auto_assigned_default == [tid]
        assert kb.get_task(conn, tid).assignee == "coder"
        assert [t.id for t in kb.list_tasks(conn, assignee="coder")] == [tid]


def test_mixed_case_default_assignee_counts_against_the_per_profile_cap(kanban_home):
    with kbc.connect() as conn:
        kb.create_task(conn, title="unassigned")
        kb.create_task(conn, title="assigned", assignee="coder")
        res = kbd.dispatch_once(
            conn, spawn_fn=lambda task, ws: None, default_assignee="Coder",
            max_in_progress_per_profile=1,
        )

        assert len(res.spawned) == 1
        assert len(res.skipped_per_profile_capped) == 1
