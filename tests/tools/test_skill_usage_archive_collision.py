"""A second archive of the same skill is keyed on the skill NAME, like the first.

The directory of a skill may differ from its name (``mlops/accelerate`` holds
``huggingface-accelerate``); restore matches ``<name>-<timestamp>``, so a duplicate keyed on
the directory name is found under the wrong skill.
"""

from pathlib import Path

import pytest


@pytest.fixture
def usage(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    (home / "skills").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    import importlib

    import tools.skill_usage as mod
    importlib.reload(mod)
    return mod, home / "skills"


def _make(mod, skills: Path) -> None:
    skill_dir = skills / "mlops" / "accelerate"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: huggingface-accelerate\ndescription: d.\n---\nbody\n")
    mod.record_created("huggingface-accelerate", agent_created=True)


def test_duplicate_archive_keeps_the_skill_name(usage):
    mod, skills = usage
    for _ in range(2):
        _make(mod, skills)
        assert mod.archive_skill("huggingface-accelerate")[0] is True

    names = sorted(p.name for p in (skills / ".archive").iterdir())
    assert names[0] == "huggingface-accelerate"
    assert names[1].startswith("huggingface-accelerate-")


def test_restore_by_directory_name_does_not_take_another_skill(usage):
    mod, skills = usage
    for _ in range(2):
        _make(mod, skills)
        mod.archive_skill("huggingface-accelerate")

    ok, _message = mod.restore_skill("accelerate")

    assert ok is False
    assert not (skills / "accelerate").exists()
