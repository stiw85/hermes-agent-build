"""``kill`` hits the hardline floor when its TARGET is -1 (every process), not when -1 is the signal.

``kill -1 <pid>`` sends SIGHUP to one process (the usual daemon reload); ``kill -s KILL -1``
signals everything the user may signal.
"""

import pytest

from tools.approval_detection import detect_hardline_command


@pytest.mark.parametrize("command", [
    "kill -1 1234",
    "kill -1 $(cat /run/nginx.pid)",
    "sudo kill -1 4321",
    "kill -1 1234 && echo reloaded",
    "kill -HUP 1234",
    "kill -9 1234; echo -1",
])
def test_signal_sent_to_one_process_is_not_hardline(command):
    is_hardline, description = detect_hardline_command(command)
    assert not is_hardline, f"expected hardline NOT to match {command!r} (got: {description})"


@pytest.mark.parametrize("command", [
    "kill -1",
    "kill -9 -1",
    "kill -1 -1",
    "kill -s KILL -1",
    "kill -s 9 -1",
    "kill -n 9 -1",
    "kill -TERM -- -1",
    "kill -9 -1 && echo gone",
    "sudo kill -s HUP -1",
])
def test_signalling_every_process_is_hardline(command):
    is_hardline, description = detect_hardline_command(command)
    assert is_hardline, f"expected hardline to match {command!r}"
    assert description == "kill all processes"
