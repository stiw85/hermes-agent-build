"""A directory whose name carries a dot is a directory, not a file to take the parent of."""

import pytest

from agent.subdirectory_hints import SubdirectoryHintTracker


@pytest.fixture
def project(tmp_path):
    for rel, text in (("packages/next.js", "Next rules"), ("conf.d", "Conf rules"), ("backend", "Backend rules")):
        directory = tmp_path / rel
        directory.mkdir(parents=True)
        (directory / "AGENTS.md").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("tool, args, expected", [
    ("search_files", {"path": "conf.d"}, "Conf rules"),
    ("terminal", {"command": "cd packages/next.js && ls"}, "Next rules"),
    ("terminal", {"command": "ls conf.d/"}, "Conf rules"),
])
def test_dotted_directory_argument_loads_its_hints(project, tool, args, expected):
    hints = SubdirectoryHintTracker(working_dir=str(project)).check_tool_call(tool, args)
    assert hints is not None and expected in hints


def test_new_file_path_still_resolves_to_its_directory(project):
    hints = SubdirectoryHintTracker(working_dir=str(project)).check_tool_call("write_file", {"path": "backend/new_module.py"})
    assert hints is not None and "Backend rules" in hints
