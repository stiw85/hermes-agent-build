"""Moving a file into a directory that does not exist yet creates it, like write_file
does: a V4A ``Move File`` must not fail half-way through an otherwise valid patch."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def ops(tmp_path):
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


def test_move_file_creates_missing_parent_directories(ops, tmp_path):
    (tmp_path / "mv.txt").write_text("y\n")

    result = ops.move_file(str(tmp_path / "mv.txt"), str(tmp_path / "new" / "dir" / "mv.txt"))

    assert result.error is None
    assert (tmp_path / "new" / "dir" / "mv.txt").read_text() == "y\n"
    assert not (tmp_path / "mv.txt").exists()


def test_v4a_move_into_new_directory_applies_whole_patch(ops, tmp_path):
    (tmp_path / "keep.txt").write_text("x\n")
    (tmp_path / "mv.txt").write_text("y\n")

    result = ops.patch_v4a(
        "*** Begin Patch\n*** Update File: keep.txt\n-x\n+X\n"
        "*** Move File: mv.txt -> pkg/mv.txt\n*** End Patch\n")

    assert result.success, result.error
    assert (tmp_path / "keep.txt").read_text() == "X\n"
    assert (tmp_path / "pkg" / "mv.txt").read_text() == "y\n"
    assert not (tmp_path / "mv.txt").exists()
