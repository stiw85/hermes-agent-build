"""ACP edit approval must inspect the file the tool will write.

``write_file``/``patch`` anchor a relative path on the session's workspace root; the adapter
process's own cwd is wherever the editor launched it.
"""

from __future__ import annotations

import json
import tempfile

import pytest

from acp_adapter.edit_approval import set_edit_approval_requester, should_auto_approve_edit
from model_tools import handle_function_call
from tools.terminal_tool import clear_task_env_overrides, register_task_env_overrides

TASK_ID = "acp-edit-approval-session-cwd"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A session workspace that is NOT the process cwd, with the temp root narrowed so
    ``tmp_path`` itself is not an auto-approve root."""
    ws = tmp_path / "workspace"
    (ws / "sub").mkdir(parents=True)
    scratch = tmp_path / "tmproot"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    register_task_env_overrides(TASK_ID, {"cwd": str(ws)})
    yield ws
    set_edit_approval_requester(None)
    clear_task_env_overrides(TASK_ID)


def test_relative_patch_is_proposed_against_the_session_workspace(workspace, tmp_path, monkeypatch):
    launch = tmp_path / "launchdir"
    launch.mkdir()
    monkeypatch.chdir(launch)
    (workspace / "a.txt").write_text("workspace original\n", encoding="utf-8")
    proposals = []

    def requester(proposal):
        proposals.append(proposal)
        return False

    set_edit_approval_requester(requester)
    result = json.loads(handle_function_call(
        "patch", {"path": "a.txt", "old_string": "original", "new_string": "edited"}, task_id=TASK_ID))

    assert [p.old_text for p in proposals] == ["workspace original\n"], result
    assert proposals[0].new_text == "workspace edited\n"
    assert "denied by acp client" in result["error"].lower()


def test_relative_escape_from_the_workspace_is_not_auto_approved(workspace, tmp_path, monkeypatch):
    # The process sits one level inside the workspace, so ``../outside.txt`` read against it
    # looks like a workspace file while the tool writes one level ABOVE the workspace.
    monkeypatch.chdir(workspace / "sub")
    set_edit_approval_requester(
        lambda proposal: should_auto_approve_edit(proposal, "workspace_session", str(workspace)))

    result = json.loads(handle_function_call(
        "write_file", {"path": "../outside.txt", "content": "x"}, task_id=TASK_ID))

    assert "denied" in str(result.get("error", "")).lower(), result
    assert not (tmp_path / "outside.txt").exists()


def test_relative_workspace_write_is_auto_approved_from_any_process_cwd(workspace, tmp_path, monkeypatch):
    launch = tmp_path / "launchdir"
    launch.mkdir()
    monkeypatch.chdir(launch)
    set_edit_approval_requester(
        lambda proposal: should_auto_approve_edit(proposal, "workspace_session", str(workspace)))

    result = json.loads(handle_function_call(
        "write_file", {"path": "new.txt", "content": "x\n"}, task_id=TASK_ID))

    assert not result.get("error"), result
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "x\n"
