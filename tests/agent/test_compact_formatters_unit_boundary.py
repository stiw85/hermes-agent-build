"""Compact duration / count labels never print a full unit of the next size down.

Rounding happened after the unit was chosen, so values just under a boundary rendered as
``60s``, ``60m``, ``1000K`` or ``1000.0K`` in the status bar, ``/usage`` and insights.
"""

import pytest

from agent.rate_limit_tracker import _fmt_count
from agent.usage_pricing import format_duration_compact, format_token_count_compact


@pytest.mark.parametrize("seconds, label", [
    (0, "0s"), (59.4, "59s"), (59.6, "1m"), (60, "1m"), (3569, "59m"), (3570, "1h"), (3599, "1h"),
    (3600, "1h"), (5400, "1h 30m"), (86399, "23h 59m"), (86400, "1.0d"),
])
def test_duration_rounds_before_choosing_the_unit(seconds, label):
    assert format_duration_compact(seconds) == label


@pytest.mark.parametrize("value, label", [
    (999, "999"), (1000, "1K"), (9995, "9.99K"), (999_499, "999K"), (999_500, "1M"), (999_999, "1M"),
    (1_000_000, "1M"), (999_999_999, "1B"), (-999_999, "-1M"), (1_500_000_000_000, "1500B"),
])
def test_token_count_rounds_before_choosing_the_unit(value, label):
    assert format_token_count_compact(value) == label


@pytest.mark.parametrize("value, label", [
    (799, "799"), (33_599, "33.6K"), (999_949, "999.9K"), (999_950, "1.0M"), (999_999, "1.0M"), (7_999_856, "8.0M"),
])
def test_rate_limit_count_rounds_before_choosing_the_unit(value, label):
    assert _fmt_count(value) == label
