"""A recurring job edited into a one-shot must still fire once.

The run history of the recurring schedule lives in ``repeat.completed``. Carried into the new
one-shot's ``times=1`` budget it reads as "limit already reached", and the due scan removed the
job at its ``run_at`` without firing it.
"""

from datetime import datetime, timedelta, UTC

import pytest

from cron import jobs


@pytest.fixture
def clock(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "cron" / "output")
    state = {"now": datetime(2026, 6, 1, 10, 0, tzinfo=UTC)}
    monkeypatch.setattr(jobs, "_hermes_now", lambda: state["now"])
    return state


def _recurring_job_with_history(clock, runs=2):
    job = jobs.create_job(prompt="digest", schedule="every 1h")
    for _ in range(runs):
        clock["now"] += timedelta(hours=1, seconds=1)
        assert [due["id"] for due in jobs.get_due_jobs()] == [job["id"]]
        jobs.advance_next_runs([job["id"]])
        jobs.mark_job_run(job["id"], success=True)
    return job["id"]


@pytest.mark.parametrize("updates", [
    {"schedule": "in 30m"},
    {"schedule": "in 30m", "repeat": 1},
    {"schedule": "in 30m", "repeat": {"times": 1, "completed": 2}},
])
def test_recurring_job_with_history_fires_after_edit_to_oneshot(clock, updates):
    job_id = _recurring_job_with_history(clock)

    jobs.update_job(job_id, updates)
    clock["now"] += timedelta(minutes=30, seconds=5)

    assert [due["id"] for due in jobs.get_due_jobs()] == [job_id]
    assert jobs.get_job(job_id) is not None


def test_same_kind_schedule_edit_keeps_the_run_count(clock):
    job_id = _recurring_job_with_history(clock)

    updated = jobs.update_job(job_id, {"schedule": "every 2h", "repeat": 5})

    assert updated["repeat"] == {"times": 5, "completed": 2}
