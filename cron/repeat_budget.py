"""The ``repeat`` budget across a schedule edit that changes the job's kind."""
from typing import Any


def rederive_repeat_for_schedule_change(job: dict[str, Any], updates: dict[str, Any]) -> None:
    """Re-derive the ``repeat`` default when a schedule update flips the kind.

    ``create_job`` derives it from the schedule kind (once -> 1, recurring -> forever); the update
    path must honour the same contract, otherwise a one-shot turned recurring keeps its ``times=1``
    budget and retires after one fire, while a recurring job turned one-shot never completes. An
    explicit ``repeat`` in the same update wins; a same-kind schedule edit leaves ``repeat`` alone.

    A job turned one-shot starts that occurrence's budget at zero, explicit ``repeat`` or not: the
    runs of the recurring schedule it replaced are not dispatches of the new one-shot, and counted
    against ``times`` they retire it at its ``run_at`` without firing.
    """
    from cron.jobs import parse_schedule  # late: jobs imports this module

    if "schedule" not in updates:
        return
    new_schedule = updates["schedule"]
    if isinstance(new_schedule, str):
        new_schedule = parse_schedule(new_schedule)
        updates["schedule"] = new_schedule
    old_kind = (job.get("schedule") or {}).get("kind")
    new_kind = new_schedule.get("kind")
    if old_kind == new_kind:
        return
    if "repeat" in updates:
        if new_kind == "once":
            explicit = updates["repeat"]
            updates["repeat"] = {
                **(explicit if isinstance(explicit, dict) else {"times": explicit}), "completed": 0}
        return
    repeat = dict(job.get("repeat") or {})
    times = repeat.get("times")
    if new_kind == "once":
        repeat["completed"] = 0
        if times is None:
            repeat["times"] = 1
    elif old_kind == "once" and times == 1:
        repeat["times"] = None
        repeat.setdefault("completed", 0)
    else:
        return
    updates["repeat"] = repeat
