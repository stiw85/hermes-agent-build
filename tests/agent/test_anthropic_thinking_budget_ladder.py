"""Manual (budget_tokens) thinking follows the effort ladder and the model's output ceiling.

Legacy Claude families and Anthropic-compatible endpoints take ``thinking.budget_tokens``. The
budget must never shrink as the requested effort grows (``max`` / ``ultra`` used to fall back to
the ``medium`` budget, ``minimal`` to more than ``low``), and the ``max_tokens`` bump that makes
room for it must stay inside the model's own output cap.
"""

import pytest

from agent.anthropic_adapter import _get_anthropic_max_output, build_anthropic_kwargs
from agent.reasoning_effort import EFFORT_LADDER

MESSAGES = [{"role": "user", "content": "hi"}]
EFFORTS = EFFORT_LADDER[1:]  # every enabled level, weakest first


def _kwargs(model: str, effort: str) -> dict:
    return build_anthropic_kwargs(model, MESSAGES, None, None, {"enabled": True, "effort": effort})


@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "claude-opus-4-1-20250805", "MiniMax-M2.7"])
def test_budget_never_shrinks_as_effort_grows(model):
    budgets = [_kwargs(model, effort)["thinking"]["budget_tokens"] for effort in EFFORTS]
    assert budgets == sorted(budgets), dict(zip(EFFORTS, budgets))
    assert budgets[EFFORTS.index("minimal")] <= budgets[EFFORTS.index("low")]
    assert budgets[EFFORTS.index("ultra")] >= budgets[EFFORTS.index("xhigh")]


@pytest.mark.parametrize("model", ["claude-opus-4-1-20250805", "claude-opus-4-20250514", "claude-sonnet-4-5"])
@pytest.mark.parametrize("effort", EFFORTS)
def test_budget_and_max_tokens_stay_inside_the_model_output_ceiling(model, effort):
    kwargs = _kwargs(model, effort)
    assert kwargs["max_tokens"] <= _get_anthropic_max_output(model)
    assert kwargs["thinking"]["budget_tokens"] < kwargs["max_tokens"]
