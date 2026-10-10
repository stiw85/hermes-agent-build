"""A negative per-token rate in a models catalog is "no fixed price", never a rate.

OpenRouter publishes ``"-1"`` for router pseudo-models (``openrouter/auto``) whose price depends
on the model the router picks. Multiplying it through billed a 12.8K-token call at -$12,800 and
reported the route as having known pricing.
"""

from decimal import Decimal

import pytest

import agent.usage_pricing as usage_pricing
from agent.usage_pricing import CanonicalUsage, estimate_usage_cost, has_known_pricing

USAGE = CanonicalUsage(input_tokens=12_000, output_tokens=800)


@pytest.fixture
def catalog(monkeypatch):
    models: dict = {}
    monkeypatch.setattr(usage_pricing, "fetch_model_metadata", lambda *a, **k: models)
    return models


def test_variable_price_sentinel_is_unknown_cost(catalog):
    catalog["openrouter/auto"] = {"pricing": {"prompt": "-1", "completion": "-1"}}
    result = estimate_usage_cost("openrouter/auto", USAGE, provider="openrouter")
    assert result.status == "unknown"
    assert result.amount_usd is None
    assert not has_known_pricing("openrouter/auto", provider="openrouter")


def test_one_negative_bucket_does_not_produce_a_partial_estimate(catalog):
    catalog["vendor/half"] = {"pricing": {"prompt": "-1", "completion": "0.000002"}}
    result = estimate_usage_cost("vendor/half", USAGE, provider="openrouter")
    assert result.status == "unknown" and result.amount_usd is None


def test_real_and_free_rates_are_still_priced(catalog):
    catalog["vendor/paid"] = {"pricing": {"prompt": "0.000001", "completion": "0.000002"}}
    catalog["vendor/free"] = {"pricing": {"prompt": "0", "completion": "0"}}
    paid = estimate_usage_cost("vendor/paid", USAGE, provider="openrouter")
    assert paid.status == "estimated" and paid.amount_usd == Decimal("0.0136")
    free = estimate_usage_cost("vendor/free", USAGE, provider="openrouter")
    assert free.amount_usd == Decimal(0)
