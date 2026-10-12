"""A line-ranged ``@file:`` read drops the UTF-8 BOM like a whole-file read does."""

from pathlib import Path

from agent.context_references import preprocess_context_references


def test_first_line_of_a_bom_file_has_no_bom(tmp_path: Path):
    (tmp_path / "notes.txt").write_bytes(b"\xef\xbb\xbffirst\nsecond\n")
    whole = preprocess_context_references("@file:notes.txt", cwd=tmp_path, context_length=100_000)
    ranged = preprocess_context_references("@file:notes.txt:1-1", cwd=tmp_path, context_length=100_000)
    assert "﻿" not in whole.message
    assert "﻿" not in ranged.message
    assert "```\nfirst\n" in ranged.message
