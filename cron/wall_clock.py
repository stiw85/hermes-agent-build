"""Attaching a zone to a schedule's wall clock ("09:00", a naive ISO timestamp).

With no ``timezone`` configured ``hermes_time.now()`` is server-local time carried as a
fixed-offset snapshot of TODAY's UTC offset. Stamped on a wall clock on the other side of a DST
change that offset is an hour off, so there the wall clock is resolved through the OS zone rules.
"""
from datetime import datetime, tzinfo
from typing import Optional

from hermes_time import get_timezone


def wall_zone(now: datetime, fallback: Optional[tzinfo] = None) -> Optional[tzinfo]:
    """Zone for wall clocks read against the scheduler clock *now*: *fallback* (default: the
    clock's own tzinfo), or None when that clock is unconfigured server-local time."""
    if get_timezone() is None and now.utcoffset() == now.astimezone().utcoffset():
        return None
    return fallback or now.tzinfo


def attach_zone(wall: datetime, zone: Optional[tzinfo]) -> datetime:
    """Naive *wall* as an aware instant in *zone*; None resolves it as server-local time on its
    own date (``fold`` is honoured either way)."""
    return wall.replace(tzinfo=zone) if zone is not None else wall.astimezone()
