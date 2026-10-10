"""``file_path`` and SKILL.md in skill_manage.

SKILL.md is the skill document: ``patch`` may name it explicitly and must then behave exactly
like the default target, while ``write_file`` / ``remove_file`` only manage supporting files
under references/ templates/ scripts/ assets/.
"""

import json
from unittest.mock import patch

import pytest

from tools.skill_manager_tool import skill_manage

SKILL = "---\nname: demo\ndescription: Demo skill.\n---\n\n# Demo\n\n## When to Use\nAlways.\n"


@pytest.fixture
def skill(tmp_path):
    with patch("tools.skill_manager_tool.SKILLS_DIR", tmp_path), \
         patch("agent.skill_utils.get_all_skills_dirs", return_value=[tmp_path]):
        assert json.loads(skill_manage(action="create", name="demo", content=SKILL))["success"]
        yield tmp_path / "demo"


def _call(**kwargs) -> dict:
    return json.loads(skill_manage(name="demo", **kwargs))


@pytest.mark.parametrize("file_path", ["SKILL.md", "./SKILL.md", "demo/SKILL.md"])
def test_explicit_skill_md_patch_is_the_default_target(skill, file_path):
    breaking = dict(action="patch", old_string="---\nname: demo", new_string="name: demo")
    default = _call(**breaking)
    explicit = _call(**breaking, file_path=file_path)

    assert default["success"] is False
    assert explicit == default
    assert (skill / "SKILL.md").read_text() == SKILL

    ok = _call(action="patch", old_string="Always.", new_string="Often.", file_path=file_path)
    assert ok["success"] is True
    assert "Often." in (skill / "SKILL.md").read_text()


def test_write_file_refuses_skill_md(skill):
    result = _call(action="write_file", file_path="SKILL.md", file_content="no frontmatter")

    assert result["success"] is False
    assert "patch" in result["error"]
    assert (skill / "SKILL.md").read_text() == SKILL


def test_remove_file_refuses_skill_md(skill):
    result = _call(action="remove_file", file_path="SKILL.md")

    assert result["success"] is False
    assert "delete" in result["error"]
    assert (skill / "SKILL.md").is_file()


@pytest.mark.parametrize("file_path", ["other/SKILL.md", "demo/SKILL.md"])
def test_write_file_stays_inside_the_supporting_dirs(skill, file_path):
    result = _call(action="write_file", file_path=file_path, file_content=SKILL)

    assert result["success"] is False
    assert sorted(p.name for p in skill.iterdir()) == ["SKILL.md"]


def test_supporting_file_named_skill_md_is_still_a_supporting_file(skill):
    result = _call(action="write_file", file_path="references/SKILL.md", file_content="# notes\n")

    assert result["success"] is True
    assert (skill / "references" / "SKILL.md").read_text() == "# notes\n"
