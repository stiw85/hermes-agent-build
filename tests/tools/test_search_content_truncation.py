"""Content search must say when the result page is not the whole answer.

File search fetches one row past the page to learn that more exist; content search
(all three output modes) has to give the same ``truncated`` signal, otherwise a
page of exactly ``limit`` rows reads as the complete result set.
"""

import json

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def ops(tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.txt").write_text("needle\n")
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


@pytest.mark.parametrize("output_mode", ["content", "files_only", "count"])
def test_page_smaller_than_result_set_is_marked_truncated(ops, tmp_path, output_mode):
    result = ops.search("needle", path=str(tmp_path), limit=3, output_mode=output_mode)

    assert result.error is None
    assert result.truncated is True
    assert result.to_dict()["total_count_is_lower_bound"] is True
    assert len(result.matches) <= 3 and len(result.files) <= 3 and len(result.counts) <= 3


@pytest.mark.parametrize("output_mode", ["content", "files_only", "count"])
def test_complete_result_set_is_not_marked_truncated(ops, tmp_path, output_mode):
    result = ops.search("needle", path=str(tmp_path), limit=6, output_mode=output_mode)

    assert result.error is None
    assert result.truncated is False
    assert result.total_count == 6


def test_search_tool_offers_next_offset_for_truncated_content(ops, tmp_path, monkeypatch):
    import tools.file_tools as file_tools

    (tmp_path / "big.txt").write_text("needle\n" * 120)
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda task_id="default": ops)

    out = json.loads(file_tools.search_tool(
        "needle", path=str(tmp_path / "big.txt"), limit=50, task_id="content-truncation"))

    assert out["truncated"] is True
    assert "offset=50" in out["_hint"]
