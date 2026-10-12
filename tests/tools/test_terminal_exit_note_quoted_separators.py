"""The informational exit-code note keys on the LAST command of the line; ``|``, ``;`` and
``&&`` inside a quoted argument are data, not command separators."""

import pytest

from tools.terminal_tool_result import _interpret_exit_code

_NO_MATCH = "No matches found (not an error)"


@pytest.mark.parametrize("command", [
    'grep -E "foo|bar" file',
    "grep 'a;b' file",
    "rg 'x && y' src",
    'cat log | grep -E "ERROR|WARN"',
    "grep foo file;",
    "grep foo file ;  ",
])
def test_grep_exit_one_note_survives_quoted_separators(command):
    assert _interpret_exit_code(command, 1) == _NO_MATCH


@pytest.mark.parametrize("command", [
    'grep -E "foo|bar" file | wc -l',
    'grep foo file; echo "grep | done" && false',
    'echo "grep" | false',
])
def test_note_still_follows_the_real_last_command(command):
    assert _interpret_exit_code(command, 1) is None


def test_diff_after_quoted_pipe_keeps_its_note():
    assert _interpret_exit_code('echo "a|b" > x; diff x y', 1) == "Files differ (expected, not an error)"
