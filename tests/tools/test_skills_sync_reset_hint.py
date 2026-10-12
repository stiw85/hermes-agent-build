"""The hint sync prints for a same-named local skill names a command that does what it says.

Plain ``hermes skills reset <name>`` only clears a manifest entry; replacing the copy needs
``--restore``. With no entry there is nothing to clear, and reset must say so.
"""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from tools.skills_sync import sync_skills
from tools.skills_sync_bundled_ops import reset_bundled_skill

LOCAL = "---\nname: foo\n---\n# My own foo\n"


@pytest.fixture
def env(tmp_path):
    """A bundled ``foo`` shipped on top of the user's own, untracked ``foo``."""
    bundled = tmp_path / "bundled_skills"
    (bundled / "category" / "foo").mkdir(parents=True)
    (bundled / "category" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\n# Stock foo\n")
    skills_dir = tmp_path / "user_skills"
    (skills_dir / "category" / "foo").mkdir(parents=True)
    (skills_dir / "category" / "foo" / "SKILL.md").write_text(LOCAL)
    with ExitStack() as stack:
        stack.enter_context(patch("tools.skills_sync._get_bundled_dir", return_value=bundled))
        stack.enter_context(patch("tools.skills_sync._get_optional_dir", return_value=tmp_path / "optional-skills"))
        stack.enter_context(patch("tools.skills_sync.SKILLS_DIR", skills_dir))
        stack.enter_context(patch("tools.skills_sync.MANIFEST_FILE", skills_dir / ".bundled_manifest"))
        yield skills_dir / "category" / "foo" / "SKILL.md"


def test_hint_names_the_command_that_replaces_the_copy(env, capsys):
    sync_skills(quiet=False)

    hint = " ".join(capsys.readouterr().out.split())
    assert "yours was kept" in hint
    assert "hermes skills reset foo --restore" in hint
    assert env.read_text() == LOCAL


def test_plain_reset_with_no_manifest_entry_reports_nothing_cleared(env):
    result = reset_bundled_skill("foo")

    assert result["ok"] is False
    assert result["action"] == "not_in_manifest"
    assert "--restore" in result["message"]
    assert env.read_text() == LOCAL


def test_restore_still_replaces_the_untracked_copy(env):
    result = reset_bundled_skill("foo", restore=True)

    assert result["ok"] is True and result["action"] == "restored"
    assert "Stock foo" in env.read_text()
