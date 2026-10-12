"""The per-platform editor of ``hermes skills`` saves only that platform's own entries.

A platform's effective list is global ∪ platform. Writing that union back copied every
globally disabled skill into ``skills.platform_disabled.<platform>``, where it then outlived
a later global re-enable.
"""

import builtins

import pytest

import hermes_cli.skills_config as skills_config
from hermes_cli.config import load_config

SKILLS = [{"name": n, "category": "c", "description": "d"} for n in ("alpha", "beta", "gamma")]


@pytest.fixture
def edit_telegram(monkeypatch):
    """Run ``hermes skills`` for Telegram, unticking the named skills in the checklist."""
    def run(untick: set[str]) -> None:
        answers = iter([str(list(skills_config.PLATFORMS).index("telegram") + 2), "1"])
        monkeypatch.setattr(builtins, "input", lambda *_: next(answers))
        monkeypatch.setattr(skills_config, "_list_all_skills", lambda: SKILLS)
        monkeypatch.setattr(
            "hermes_cli.curses_ui.curses_checklist",
            lambda _title, _labels, pre_selected, cancel_returns=None: {
                i for i in pre_selected if SKILLS[i]["name"] not in untick})
        skills_config.skills_command()
    return run


def test_platform_list_holds_only_platform_entries(edit_telegram):
    skills_config.save_disabled_skills(load_config(), {"alpha"})

    edit_telegram({"beta"})

    skills = load_config()["skills"]
    assert skills["disabled"] == ["alpha"]
    assert skills["platform_disabled"]["telegram"] == ["beta"]


def test_global_re_enable_reaches_an_edited_platform(edit_telegram):
    skills_config.save_disabled_skills(load_config(), {"alpha"})
    edit_telegram({"beta"})

    skills_config.save_disabled_skills(load_config(), set())

    assert skills_config.get_disabled_skills(load_config(), "telegram") == {"beta"}
