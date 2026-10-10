"""``agent.max_turns`` given as a non-finite number.

The string spellings ``inf`` / ``infinity`` mean unlimited; YAML's own float form (``.inf``) and
an overflowing literal (``1e999``, also via ``HERMES_MAX_ITERATIONS``) must mean the same instead
of crashing CLI init, gateway startup and cron with ``OverflowError``. NaN is unparseable.
"""

import pytest

from hermes_cli.config import TURN_LIMIT_UNLIMITED, fast_safe_load, resolve_turn_limit


@pytest.mark.parametrize("raw", [float("inf"), float("-inf"), "1e999", " -1E999 "])
def test_infinite_values_mean_unlimited(raw):
    assert resolve_turn_limit(raw, default=90) == TURN_LIMIT_UNLIMITED


@pytest.mark.parametrize("raw", [float("nan"), "nan"])
def test_nan_falls_back_to_the_default(raw):
    assert resolve_turn_limit(raw, default=90) == 90


def test_yaml_inf_in_config_resolves_to_unlimited():
    raw = fast_safe_load("agent:\n  max_turns: .inf\n")["agent"]["max_turns"]

    assert resolve_turn_limit(raw) == TURN_LIMIT_UNLIMITED
