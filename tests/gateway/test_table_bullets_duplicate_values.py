"""Table → bullets keeps every cell: only the cell used as the row heading is omitted."""

from gateway.platforms.helpers import convert_table_to_bullets


def test_cell_equal_to_the_heading_value_is_kept():
    out = convert_table_to_bullets("| Name | Status | Owner |\n|---|---|---|\n| api | ok | api |")
    assert out == "**api**\n• Status: ok\n• Owner: api"


def test_row_of_identical_values_keeps_the_other_columns():
    out = convert_table_to_bullets("| Q1 | Q2 | Q3 |\n|---|---|---|\n| 7 | 7 | 7 |")
    assert out == "**7**\n• Q2: 7\n• Q3: 7"


def test_heading_taken_from_a_later_cell_omits_that_cell_only():
    out = convert_table_to_bullets("| Name | Score |\n|---|---|\n|  | 5 |")
    assert out == "**5**\n• Name: "
