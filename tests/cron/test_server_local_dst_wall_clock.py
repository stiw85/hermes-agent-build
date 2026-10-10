"""With no ``timezone`` configured the scheduler runs on server-local time, and that clock's
UTC offset changes at DST.

``hermes_time.now()`` then carries a fixed-offset snapshot of TODAY's offset. Stamping it on a
wall clock on the other side of a DST change stored ``0 9 * * *`` as 10:00 local for the first
fire after spring-forward, and a naive one-shot timestamp an hour off.
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import hermes_time
from cron import jobs

pytest.importorskip("croniter")
pytestmark = pytest.mark.platforms("posix")  # needs a process timezone switch (time.tzset)

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture
def new_york_server(tmp_path, monkeypatch):
    """A server whose OS zone is America/New_York and whose Hermes ``timezone`` is unset."""
    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "cron" / "output")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    hermes_time.reset_cache()

    def at(*wall):
        # Exactly what hermes_time.now() returns at that instant on this server.
        instant = datetime(*wall, tzinfo=NEW_YORK).timestamp()
        monkeypatch.setattr(jobs, "_hermes_now", lambda: datetime.fromtimestamp(instant).astimezone())

    try:
        assert hermes_time.get_timezone() is None
        yield at
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
        hermes_time.reset_cache()


def _local(iso):
    return datetime.fromisoformat(iso).astimezone(NEW_YORK)


@pytest.mark.parametrize("day_before, transition_day", [
    ((2026, 3, 7, 10, 0), 8),    # spring-forward: Sunday 8 March
    ((2026, 10, 31, 10, 0), 1),  # fall-back: Sunday 1 November
])
def test_daily_cron_keeps_its_wall_clock_hour_across_a_dst_change(
        new_york_server, day_before, transition_day):
    new_york_server(*day_before)

    nxt = _local(jobs.compute_next_run({"kind": "cron", "expr": "0 9 * * *"}))

    assert (nxt.day, nxt.hour, nxt.minute) == (transition_day, 9, 0)


def test_morning_job_is_due_at_nine_local_after_spring_forward(new_york_server):
    new_york_server(2026, 3, 7, 10, 0)
    job = jobs.create_job(prompt="morning brief", schedule="0 9 * * *")

    new_york_server(2026, 3, 8, 9, 0, 30)

    assert [due["id"] for due in jobs.get_due_jobs()] == [job["id"]]


@pytest.mark.parametrize("created, timestamp", [
    ((2026, 10, 10, 12, 0), "2026-12-25T09:00:00"),  # created in EDT for a date in EST
    ((2026, 1, 10, 12, 0), "2026-07-04T09:00:00"),   # created in EST for a date in EDT
])
def test_naive_oneshot_timestamp_means_local_wall_clock_on_its_own_date(
        new_york_server, created, timestamp):
    new_york_server(*created)

    run_at = _local(jobs.parse_schedule(timestamp)["run_at"])

    assert run_at.replace(tzinfo=None) == datetime.fromisoformat(timestamp)
