"""Slack's fenced table keeps a GFM ``\\|`` inside its cell."""

from plugins.platforms.slack.adapter import _align_table


def test_escaped_pipe_does_not_add_a_column():
    rows = ["| Param | Type |", "|---|---|", r"| timeout | int \| None |"]
    assert _align_table(rows) == [
        "| Param   | Type       |",
        "| ------- | ---------- |",
        "| timeout | int | None |",
    ]
