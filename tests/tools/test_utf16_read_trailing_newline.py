"""A UTF-16 file reads with the same line accounting as its UTF-8 twin: the newline
that ends the last line does not start another one, and an offset past the end is
named as such instead of rendering an empty numbered line."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations

_TEXT = "one\ntwo\n"


@pytest.fixture
def ops(tmp_path):
    (tmp_path / "u8.txt").write_bytes(_TEXT.encode("utf-8"))
    (tmp_path / "u16.txt").write_bytes(_TEXT.encode("utf-16"))
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


@pytest.mark.parametrize("offset,limit", [(1, 2000), (2, 1), (1, 1)])
def test_pages_match_the_utf8_twin(ops, tmp_path, offset, limit):
    utf8 = ops.read_file(str(tmp_path / "u8.txt"), offset, limit)
    utf16 = ops.read_file(str(tmp_path / "u16.txt"), offset, limit)

    assert (utf16.content, utf16.total_lines, utf16.truncated) == (utf8.content, utf8.total_lines, utf8.truncated)
    assert utf16.total_lines == 2


@pytest.mark.parametrize("offset", [3, 9])
def test_offset_past_end_is_reported(ops, tmp_path, offset):
    result = ops.read_file(str(tmp_path / "u16.txt"), offset, 1)

    assert result.content == ""
    assert result.total_lines == 2
    assert "beyond the end of the file" in result.hint
