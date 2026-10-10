"""A GFM ``\\|`` is cell content, not a column separator."""

from agent.markdown_tables import realign_markdown_tables, split_table_row


def test_escaped_pipe_stays_inside_its_cell():
    assert split_table_row(r"| timeout | `int \| None` |") == ["timeout", "`int | None`"]
    assert split_table_row(r"a \| b | c") == ["a | b", "c"]


def test_realigned_table_keeps_its_column_count():
    src = "| Param | Type |\n|---|---|\n| timeout | `int \\| None` |\n| retries | int |"
    assert realign_markdown_tables(src).split("\n") == [
        "| Param   | Type         |",
        "|---------|--------------|",
        "| timeout | `int | None` |",
        "| retries | int          |",
    ]
