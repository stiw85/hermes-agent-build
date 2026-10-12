"""An archived parent is terminal for dependency gating at creation time too:
a child created under it is ``ready``, never an unexplained ``todo``."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_child_of_archived_parent_is_created_ready(kanban_home):
    with kbc.connect() as conn:
        parent = kb.create_task(conn, title="parent")
        kb.archive_task(conn, parent)

        child = kb.create_task(conn, title="child", parents=[parent])

        assert kb.get_task(conn, child).status == "ready"
        assert kb.unsatisfied_parents(conn, child) == []


def test_child_of_open_parent_still_waits(kanban_home):
    with kbc.connect() as conn:
        done = kb.create_task(conn, title="archived parent")
        kb.archive_task(conn, done)
        open_parent = kb.create_task(conn, title="open parent")

        child = kb.create_task(conn, title="child", parents=[done, open_parent])

        assert kb.get_task(conn, child).status == "todo"
        assert [e.kind for e in kb.list_events(conn, child)][-1] == "dependency_wait"
