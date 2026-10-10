"""Vertex token freshness is judged in UTC, whatever the process timezone.

google-auth stores ``Credentials.expiry`` as a NAIVE datetime in UTC. Reading it as local time
made every freshly minted one-hour token look expired east of UTC (a blocking OAuth re-mint on
every credential lookup) and hid the five-minute early-refresh window west of UTC.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.vertex_adapter import _needs_refresh

pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs a POSIX process timezone switch")


@pytest.fixture
def process_tz():
    original = os.environ.get("TZ")

    def switch(name: str) -> None:
        os.environ["TZ"] = name
        time.tzset()

    yield switch
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


def _creds(expires_in: timedelta) -> SimpleNamespace:
    """A token as google-auth holds it: ``expiry`` is naive and in UTC."""
    naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(token="ya29.fresh", expired=False, expiry=naive_utc_now + expires_in)


@pytest.mark.parametrize("zone", ["UTC", "Australia/Perth", "Europe/Berlin", "America/Los_Angeles"])
def test_fresh_one_hour_token_is_not_refreshed(process_tz, zone):
    process_tz(zone)
    assert _needs_refresh(_creds(timedelta(hours=1))) is False


@pytest.mark.parametrize("zone", ["UTC", "Australia/Perth", "America/Los_Angeles"])
def test_token_inside_the_five_minute_window_is_refreshed(process_tz, zone):
    process_tz(zone)
    assert _needs_refresh(_creds(timedelta(minutes=2))) is True
