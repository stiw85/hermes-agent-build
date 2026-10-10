"""A patch adapts the text it substitutes to the file's line ending; it does not
rewrite the terminators (or lone carriage returns) of lines it never touched."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def ops(tmp_path):
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


def test_lone_carriage_return_in_untouched_line_of_lf_file_survives(ops, tmp_path):
    target = tmp_path / "fixture.txt"
    target.write_bytes(b"spinner: |\r/\r-\rdone\nname = old\n")

    result = ops.patch_replace(str(target), "name = old", "name = new")

    assert result.error is None
    assert target.read_bytes() == b"spinner: |\r/\r-\rdone\nname = new\n"


def test_crlf_lines_beyond_the_sniffed_head_of_lf_file_survive(ops, tmp_path):
    target = tmp_path / "mixed.txt"
    target.write_bytes(b"x\n" * 2100 + b"keep\r\ntarget\n")

    result = ops.patch_replace(str(target), "target", "TARGET")

    assert result.error is None
    assert target.read_bytes() == b"x\n" * 2100 + b"keep\r\nTARGET\n"


def test_lone_carriage_return_in_crlf_file_survives_v4a_update(ops, tmp_path):
    target = tmp_path / "v.txt"
    target.write_bytes(b"bar: a\rb\r\nname = old\r\n")

    result = ops.patch_v4a(
        "*** Begin Patch\n*** Update File: v.txt\n-name = old\n+name = new\n*** End Patch\n")

    assert result.success, result.error
    assert target.read_bytes() == b"bar: a\rb\r\nname = new\r\n"


def test_crlf_replacement_text_is_adapted_to_lf_file(ops, tmp_path):
    target = tmp_path / "lf.txt"
    target.write_bytes(b"a\nb\nc\n")

    result = ops.patch_replace(str(target), "b", "b1\r\nb2")

    assert result.error is None
    assert target.read_bytes() == b"a\nb1\nb2\nc\n"
