"""A SKILL.md whose frontmatter ``name`` is not a string still lists and loads.

YAML reads ``name: 2048`` as an int and ``name:`` as null; the catalog must fall back the way
the prompt index does instead of dropping the skill.
"""

import json
from unittest.mock import patch

import pytest

from tools.skills_tool import _find_all_skills, skill_view


def _skill(root, directory, frontmatter):
    skill_dir = root / directory
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n# Title\n\nBody.\n")


@pytest.fixture
def skills_dir(tmp_path):
    with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
        yield tmp_path


def test_numeric_name_is_listed_and_loadable(skills_dir):
    _skill(skills_dir, "game-2048", "name: 2048\ndescription: Play 2048.")

    assert [s["name"] for s in _find_all_skills()] == ["2048"]
    assert json.loads(skill_view("2048"))["success"] is True


def test_empty_name_falls_back_to_the_directory(skills_dir):
    _skill(skills_dir, "empty-name", "name:\ndescription: Name left empty.")

    assert [s["name"] for s in _find_all_skills()] == ["empty-name"]
    viewed = json.loads(skill_view("empty-name"))
    assert viewed["success"] is True
    assert viewed["name"] == "empty-name"
