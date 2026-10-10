"""A V4A hunk header names the enclosing scope so a change that occurs several times
in the file lands in the right place. Validation has to honour the hint exactly as
the apply phase does, in both header spellings (``@@ hint @@`` and ``@@ hint``)."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.patch_parser import parse_v4a_patch

_FILLER = "".join(f"# filler line {i}\n" for i in range(200))
_SOURCE = "def a():\n    return 1\n\n" + _FILLER + "\ndef b():\n    return 1\n"


@pytest.fixture
def ops(tmp_path):
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


@pytest.mark.parametrize("header", ["@@ def b(): @@", "@@ def b():"])
def test_hint_selects_the_occurrence_inside_the_named_scope(ops, tmp_path, header):
    target = tmp_path / "r.py"
    target.write_text(_SOURCE)

    result = ops.patch_v4a(
        f"*** Begin Patch\n*** Update File: r.py\n{header}\n-    return 1\n+    return 2\n*** End Patch\n")

    assert result.success, result.error
    assert target.read_text() == _SOURCE[:-len("    return 1\n")] + "    return 2\n"


def test_ambiguous_change_without_hint_is_still_rejected(ops, tmp_path):
    target = tmp_path / "r.py"
    target.write_text(_SOURCE)

    result = ops.patch_v4a(
        "*** Begin Patch\n*** Update File: r.py\n@@\n-    return 1\n+    return 2\n*** End Patch\n")

    assert not result.success
    assert "Found 2 matches" in result.error
    assert target.read_text() == _SOURCE


def test_header_spellings_parse_to_the_same_hint():
    for header, expected in (("@@ def b(): @@", "def b():"), ("@@ def b():", "def b():"),
                             ("@@", None), ("@@ @@", None)):
        ops_, err = parse_v4a_patch(f"*** Update File: f.py\n{header}\n-a\n+b\n")
        assert err is None
        assert ops_[0].hunks[0].context_hint == expected, header
