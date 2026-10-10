"""Tool duration labels pick their unit from the value they display."""

from __future__ import annotations

import pytest

from tui_gateway import server


@pytest.mark.parametrize("seconds,label", [
    (None, ""), (0, "0.0s"), (9.94, "9.9s"), (9.96, "10s"), (10, "10s"), (59.4, "59s"),
    (59.5, "1m"), (59.9, "1m"), (60, "1m"), (61.2, "1m 1s"), (119.6, "2m"), (125, "2m 5s"),
])
def test_tool_duration_label(seconds, label):
    assert server._fmt_tool_duration(seconds) == label
