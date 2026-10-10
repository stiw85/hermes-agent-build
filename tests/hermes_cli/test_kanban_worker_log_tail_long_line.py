"""``read_worker_log(tail_bytes=N)`` returns the tail even when the log's
last line is longer than the window."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    d = kb.worker_logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_tail_of_a_long_newline_terminated_last_line(log_dir):
    (log_dir / "t_long.log").write_text("boot ok\n" + "E" * 300 + " quota exhausted\n", encoding="utf-8")

    tail = kb.read_worker_log("t_long", tail_bytes=100)

    assert tail.endswith(" quota exhausted\n")
    assert len(tail) == 100


def test_tail_still_drops_a_partial_first_line(log_dir):
    (log_dir / "t_lines.log").write_text("".join(f"line {i}\n" for i in range(10)), encoding="utf-8")

    assert kb.read_worker_log("t_lines", tail_bytes=17) == "line 8\nline 9\n"


def test_crash_reason_survives_a_long_final_line(log_dir):
    (log_dir / "t_err.log").write_text(
        "starting\n" + "x" * 5000 + " credit balance too low\n", encoding="utf-8")

    assert kbd._worker_final_output("t_err").endswith("credit balance too low")
