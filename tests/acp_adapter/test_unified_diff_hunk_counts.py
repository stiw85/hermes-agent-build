"""Diff content lines that look like file headers stay inside their hunk."""

from __future__ import annotations

from acp_adapter.tools import _parse_unified_diff_content


def test_removed_and_added_double_dash_lines_are_content():
    diff = (
        "--- a/skills/x/SKILL.md\n"
        "+++ b/skills/x/SKILL.md\n"
        "@@ -1,4 +1,4 @@\n"
        " SELECT 1;\n"
        "--- old comment\n"
        "+-- new comment\n"
        " SELECT 2;\n"
        " SELECT 3;\n"
    )

    blocks = _parse_unified_diff_content(diff)

    assert [b.path for b in blocks] == ["skills/x/SKILL.md"]
    assert blocks[0].old_text == "SELECT 1;\n-- old comment\nSELECT 2;\nSELECT 3;"
    assert blocks[0].new_text == "SELECT 1;\n-- new comment\nSELECT 2;\nSELECT 3;"


def test_added_double_plus_line_does_not_rename_the_file():
    diff = (
        "--- a/notes.md\n"
        "+++ b/notes.md\n"
        "@@ -1 +1,2 @@\n"
        " i\n"
        "+++ j\n"
    )

    blocks = _parse_unified_diff_content(diff)

    assert [(b.path, b.old_text, b.new_text) for b in blocks] == [("notes.md", "i", "i\n++ j")]


def test_two_files_and_two_hunks_still_split_per_file():
    diff = (
        "--- a/one.txt\n+++ b/one.txt\n@@ -1 +1 @@\n-a\n+b\n@@ -9 +9 @@\n-c\n+d\n"
        "--- a/two.txt\n+++ b/two.txt\n@@ -1,2 +1,2 @@\n x\n-y\n+z\n"
    )

    blocks = _parse_unified_diff_content(diff)

    assert [(b.path, b.old_text, b.new_text) for b in blocks] == [
        ("one.txt", "a\nc", "b\nd"), ("two.txt", "x\ny", "x\nz")]
