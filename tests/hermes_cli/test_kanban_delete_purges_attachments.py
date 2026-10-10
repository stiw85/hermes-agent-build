"""Hard-deleting a task removes its attachments: the rows and the stored files."""

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


def _delete(conn, tid):
    return kb.delete_task(conn, tid)


def _archive_then_purge(conn, tid):
    kb.archive_task(conn, tid)
    return kb.delete_archived_task(conn, tid)


@pytest.mark.parametrize("remove", [_delete, _archive_then_purge])
def test_deleting_a_task_removes_attachment_rows_and_files(kanban_home, remove):
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="has a file")
        att_id = kb.store_attachment_bytes(conn, tid, "notes.pdf", b"x" * 64)
        blob = Path(kb.get_attachment(conn, att_id).stored_path)
        assert blob.is_file()

        assert remove(conn, tid) is True

        assert kb.get_attachment(conn, att_id) is None
        assert kb.list_attachments(conn, tid) == []
        assert not blob.exists()
        assert not blob.parent.exists()


def test_refused_delete_keeps_the_attachment(kanban_home):
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="still live")
        att_id = kb.store_attachment_bytes(conn, tid, "notes.pdf", b"x")
        blob = Path(kb.get_attachment(conn, att_id).stored_path)

        assert kb.delete_archived_task(conn, tid) is False  # not archived

        assert kb.get_attachment(conn, att_id) is not None
        assert blob.is_file()


def test_delete_keeps_a_file_another_task_still_references(kanban_home):
    with kbc.connect() as conn:
        doomed = kb.create_task(conn, title="doomed")
        keeper = kb.create_task(conn, title="keeper")
        att_id = kb.store_attachment_bytes(conn, doomed, "shared.txt", b"shared")
        blob = Path(kb.get_attachment(conn, att_id).stored_path)
        kb.add_attachment(conn, keeper, filename="shared.txt", stored_path=str(blob), size=6)

        assert kb.delete_task(conn, doomed) is True

        assert blob.is_file()
        assert [a.stored_path for a in kb.list_attachments(conn, keeper)] == [str(blob)]
