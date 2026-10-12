"""With ``context`` set, a context line keeps its file and line number even when its
text looks like a separator itself (timestamps ``12:30:44``, dates ``2026-10-10``,
slices ``a[1:2:3]``)."""

import os

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations

_LOG = ("2026-10-10 12:30:44 INFO boot\n"
        "2026-10-10 12:30:45 INFO ready\n"
        "ERROR needle\n"
        "retry in 5-10-15 s\n"
        "range a[1:2:3]\n")


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "app.log").write_text(_LOG)
    return tmp_path


def _rows(result):
    return [(os.path.basename(m.path), m.line_number, m.content) for m in result.matches]


@pytest.mark.parametrize("path", ["app.log", "."])
def test_context_lines_keep_path_line_and_text(tree, path):
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tree)), cwd=str(tree))

    result = ops.search("needle", path=path, context=2)

    assert result.error is None
    assert _rows(result) == [("app.log", n, text) for n, text in enumerate(_LOG.splitlines(), start=1)]


def test_grep_engine_parses_the_same_context_lines(tree, monkeypatch):
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tree)), cwd=str(tree))
    monkeypatch.setattr(ops, "_has_command", lambda cmd: cmd == "grep")

    result = ops.search("needle", path="app.log", context=2)

    assert result.error is None
    assert _rows(result) == [("app.log", n, text) for n, text in enumerate(_LOG.splitlines(), start=1)]
