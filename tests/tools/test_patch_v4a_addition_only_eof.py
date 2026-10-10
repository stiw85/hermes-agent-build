"""An addition-only V4A hunk with no usable anchor appends at end of file: after the
existing bytes, separated by exactly the newline the file was missing."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def ops(tmp_path):
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


@pytest.mark.parametrize("before,after", [
    (b"", b"hello\n"),
    (b"a\n\n\n", b"a\n\n\nhello\n"),
    (b"a\n", b"a\nhello\n"),
    (b"a", b"a\nhello\n"),
])
def test_append_keeps_existing_bytes(ops, tmp_path, before, after):
    target = tmp_path / "t.txt"
    target.write_bytes(before)

    result = ops.patch_v4a("*** Begin Patch\n*** Update File: t.txt\n+hello\n*** End Patch\n")

    assert result.success, result.error
    assert target.read_bytes() == after
