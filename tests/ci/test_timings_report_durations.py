"""scripts/ci/timings_report.py: durations never render a 60-second remainder."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "timings_report.py"
_spec = importlib.util.spec_from_file_location("timings_report", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.mark.parametrize("seconds, text", [
    (None, "—"), (0.0, "0.0s"), (59.94, "59.9s"), (59.96, "1m"), (60.0, "1m"), (60.4, "1m"),
    (119.4, "1m59s"), (119.6, "2m"), (125.0, "2m5s"), (3599.7, "60m"),
])
def test_fmt_dur_rounds_before_splitting_minutes(seconds, text):
    assert _mod.fmt_dur(seconds) == text
