"""``output_mode="files_only"`` lists every matching file, including those whose
path contains spaces (a bare path line is payload, not a tool diagnostic)."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.file_operations_search import _split_tool_diagnostics


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "My Docs").mkdir()
    (tmp_path / "My Docs" / "notes file.txt").write_text("needle here\n")
    (tmp_path / "plain.txt").write_text("needle\n")
    return tmp_path


def test_files_only_lists_paths_with_spaces(tree):
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tree)), cwd=str(tree))

    result = ops.search("needle", path=".", output_mode="files_only")

    assert result.error is None
    assert sorted(f.removeprefix("./") for f in result.files) == ["My Docs/notes file.txt", "plain.txt"]
    assert result.total_count == 2


def test_files_only_inside_directory_with_spaces_has_no_false_zero_match_warning(tree):
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tree)), cwd=str(tree))

    result = ops.search("needle", path="My Docs", output_mode="files_only")

    assert [f.removeprefix("./") for f in result.files] == ["My Docs/notes file.txt"]
    assert result.warning is None


def test_bare_path_with_spaces_is_payload_and_diagnostics_stay_diagnostics():
    diagnostics, payload = _split_tool_diagnostics(
        "My Docs/notes file.txt\nplain.txt\n"
        "rg: regex parse error:\n    (?:foo()\n    ^\nerror: unclosed group\n")

    assert payload.split("\n") == ["My Docs/notes file.txt", "plain.txt"]
    assert "error: unclosed group" in diagnostics and "regex parse error" in diagnostics
