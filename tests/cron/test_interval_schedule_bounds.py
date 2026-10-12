"""A recurring interval must be at least one minute, and a duration is a duration in any case.

``every 0m`` used to store ``minutes: 0``: due the instant it was created and again on every
scheduler tick, a full agent run each time. Upper-case units containing a ``T`` (``30 MINUTES``)
were mistaken for an ISO timestamp and rejected as one.
"""

import pytest

from cron.jobs import create_job, load_jobs, parse_schedule


@pytest.mark.parametrize("schedule", ["0m", "every 0m", "every 0 minutes", "every 0h", "0d"])
def test_zero_length_interval_is_rejected(schedule):
    with pytest.raises(ValueError):
        parse_schedule(schedule)


def test_zero_length_interval_never_reaches_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")

    with pytest.raises(ValueError, match="at least 1 minute"):
        create_job(prompt="ping", schedule="every 0m")

    assert load_jobs() == []


def test_run_once_now_is_still_a_valid_oneshot():
    assert parse_schedule("in 0m")["kind"] == "once"


@pytest.mark.parametrize("schedule, minutes", [
    ("30 MINUTES", 30), ("10 MINUTE", 10), ("EVERY 2 HOURS", 120), ("30 minutes", 30),
])
def test_recurring_duration_parses_in_any_case(schedule, minutes):
    assert parse_schedule(schedule) == {
        "kind": "interval", "minutes": minutes, "display": f"every {minutes}m"}


def test_oneshot_duration_parses_in_any_case():
    assert parse_schedule("in 30 MINUTES")["kind"] == "once"


@pytest.mark.parametrize("schedule", ["Tomorrow", "2026-13-01T09:00:00"])
def test_malformed_timestamp_is_still_reported_as_a_timestamp(schedule):
    with pytest.raises(ValueError, match="Invalid timestamp"):
        parse_schedule(schedule)
