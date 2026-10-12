"""Empty lines inside a V4A hunk are content: an empty line between two added lines
is an added blank line, an empty line elsewhere in a hunk is blank context (models
and transports strip the lone leading space). ``*** End of File`` is a marker, not
context."""

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.patch_parser import parse_v4a_patch


@pytest.fixture
def ops(tmp_path):
    return ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))


def _patch(body: str) -> str:
    return "*** Begin Patch\n" + body + "*** End Patch\n"


def test_blank_lines_between_added_lines_are_added(ops, tmp_path):
    target = tmp_path / "a.py"
    target.write_text("import os\n")

    result = ops.patch_v4a(_patch(
        "*** Update File: a.py\n import os\n+\n+def one():\n+    pass\n\n\n+def two():\n+    pass\n"))

    assert result.success, result.error
    assert target.read_text() == "import os\n\ndef one():\n    pass\n\n\ndef two():\n    pass\n"


def test_blank_lines_in_added_file_are_kept(ops, tmp_path):
    result = ops.patch_v4a(_patch("*** Add File: n.md\n+title\n\n+body\n\n"))

    assert result.success, result.error
    assert (tmp_path / "n.md").read_text() == "title\n\nbody"


def test_blank_context_line_without_its_leading_space_matches(ops, tmp_path):
    target = tmp_path / "b.py"
    target.write_text("a = 1\n\nb = 2\nc = 3\n")

    result = ops.patch_v4a(_patch("*** Update File: b.py\n@@\n a = 1\n\n-b = 2\n+b = 20\n c = 3\n"))

    assert result.success, result.error
    assert target.read_text() == "a = 1\n\nb = 20\nc = 3\n"


def test_end_of_file_marker_is_not_context(ops, tmp_path):
    target = tmp_path / "c.txt"
    target.write_text("a\nb\n")

    result = ops.patch_v4a(_patch("*** Update File: c.txt\n@@\n a\n-b\n+c\n*** End of File\n"))

    assert result.success, result.error
    assert target.read_text() == "a\nc\n"


def test_empty_lines_around_hunks_and_operations_add_nothing():
    ops_, err = parse_v4a_patch(_patch(
        "*** Update File: f.py\n\n@@ one @@\n\n a\n-b\n+c\n\n@@ two @@\n-x\n+y\n\n\n*** Delete File: g.py\n\n"))

    assert err is None
    assert [[(l.prefix, l.content) for l in h.lines] for h in ops_[0].hunks] == [
        [(" ", "a"), ("-", "b"), ("+", "c")], [("-", "x"), ("+", "y")]]
