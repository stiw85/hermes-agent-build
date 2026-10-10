"""Board import parks every task the dispatcher would still pick up whose
dir/worktree workspace did not travel: the review lane and breaker-parked
cards included. Operator- and worker-blocked cards stay where they were."""

from __future__ import annotations

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_transfer as kt


@pytest.fixture
def kanban_root(tmp_path, monkeypatch):
    """Re-point kanban at a fresh root per call ("the other machine")."""
    def _use(name: str):
        root = tmp_path / name
        root.mkdir(exist_ok=True)
        monkeypatch.setenv("HERMES_HOME", str(root))
        monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
        for var in ("HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT",
                    "HERMES_KANBAN_ATTACHMENTS_ROOT", "HERMES_KANBAN_BOARD"):
            monkeypatch.delenv(var, raising=False)
        kb._INITIALIZED_PATHS.clear()
        return root

    _use("source")
    return _use


def _round_trip(kanban_root, tmp_path):
    archive = kt.export_board(None, str(tmp_path / "board"))["archive"]
    kanban_root("target")
    return kt.import_board(archive, "imported")["board"]


def _statuses(board):
    with kbc.connect_closing(board=board) as conn:
        return {t.title: t.status for t in kb.list_tasks(conn)}


def test_import_parks_review_task_with_local_workspace(kanban_root, tmp_path):
    workdir = tmp_path / "proj"
    workdir.mkdir()
    with kbc.connect_closing() as conn:
        tid = kb.create_task(conn, title="in review", assignee="dev",
                             workspace_kind="dir", workspace_path=str(workdir))
        kb.claim_task(conn, tid)
        assert kb.request_review(conn, tid, summary="please review", reviewer="rev", force=True)

    board = _round_trip(kanban_root, tmp_path)

    assert _statuses(board) == {"in review": "triage"}


def test_import_parks_breaker_blocked_task_but_not_an_explicit_block(kanban_root, tmp_path):
    workdir = tmp_path / "proj"
    workdir.mkdir()
    with kbc.connect_closing() as conn:
        tripped = kb.create_task(conn, title="breaker", assignee="dev",
                                 workspace_kind="dir", workspace_path=str(workdir))
        for _ in range(2):
            kbd._record_task_failure(conn, tripped, "boom", outcome="crashed", failure_limit=2)
        assert kb.get_task(conn, tripped).status == "blocked"
        held = kb.create_task(conn, title="needs input", assignee="dev",
                              workspace_kind="dir", workspace_path=str(workdir))
        kb.claim_task(conn, held)
        assert kb.block_task(conn, held, reason="waiting on a human")

    board = _round_trip(kanban_root, tmp_path)

    assert _statuses(board) == {"breaker": "triage", "needs input": "blocked"}
    # Nothing left for a tick to resume into a workspace that is not there.
    with kbc.connect_closing(board=board) as conn:
        assert kb.recompute_ready(conn) == 0
