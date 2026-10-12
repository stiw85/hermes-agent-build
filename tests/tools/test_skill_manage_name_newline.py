"""skill_manage names and categories are single filesystem-safe tokens.

``$`` also matches just before a trailing newline, so a name such as ``"demo\\n"`` passed the
rule and became a directory whose name ends in a newline; a category was validated stripped
but used verbatim.
"""

import json
from unittest.mock import patch

import pytest

from tools.skill_manager_tool import _validate_category, _validate_name, skill_manage

SKILL = "---\nname: demo\ndescription: Demo skill.\n---\n\n# Demo\n\n## When to Use\nAlways.\n"


@pytest.fixture
def skills_dir(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    with patch("tools.skill_manager_tool.SKILLS_DIR", root), \
         patch("agent.skill_utils.get_all_skills_dirs", return_value=[root]):
        yield root


@pytest.mark.parametrize("name", ["demo\n", "demo\r\n", "a\n"])
def test_name_ending_in_a_newline_is_rejected(name):
    assert _validate_name(name) is not None


def test_create_with_newline_name_writes_nothing(skills_dir):
    result = json.loads(skill_manage(action="create", name="demo\n", content=SKILL))

    assert result["success"] is False
    assert [p.name for p in skills_dir.iterdir() if not p.name.startswith(".")] == []


def test_category_is_used_as_validated(skills_dir):
    assert _validate_category(" tools \n") is None

    result = json.loads(skill_manage(action="create", name="demo", content=SKILL, category=" tools \n"))

    assert result["success"] is True
    assert (skills_dir / "tools" / "demo" / "SKILL.md").is_file()
    assert sorted(p.name for p in skills_dir.iterdir() if not p.name.startswith(".")) == ["tools"]
