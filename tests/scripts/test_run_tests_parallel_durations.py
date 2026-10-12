"""The duration cache is advisory: an unreadable one is reported and ignored."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "rtp_durations", Path(__file__).resolve().parents[2] / "scripts" / "run_tests_parallel.py")
rtp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtp)


def test_corrupt_cache_is_empty_and_the_message_names_the_parse_error(tmp_path, capsys):
    (tmp_path / "test_durations.json").write_text("{not json", encoding="utf-8")
    assert rtp._load_durations(tmp_path) == {}
    out = capsys.readouterr().out
    assert "{e}" not in out
    assert "line 1" in out


def test_cache_that_is_not_a_mapping_is_empty(tmp_path):
    (tmp_path / "test_durations.json").write_text("[1, 2]", encoding="utf-8")
    assert rtp._load_durations(tmp_path) == {}
