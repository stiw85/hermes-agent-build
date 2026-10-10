"""Catalog keys written in the provider's own casing resolve.

Hugging Face style ids (``deepseek-ai/DeepSeek-V3.2``) are stored as published; the lookup
lower-cases the model id, so a case-sensitive test against the raw key could never hit and the
model fell to its family catch-all (128K for a 65,536-token model). An ``org/name`` key names one
model exactly: it must not capture a longer sibling id (``zai-org/GLM-5.3``).
"""

import pytest

from agent.model_metadata import DEFAULT_CONTEXT_LENGTHS, _longest_key_match

ORG_KEYS = [key for key in DEFAULT_CONTEXT_LENGTHS if "/" in key]


def _resolve(model: str) -> int:
    hit = _longest_key_match(DEFAULT_CONTEXT_LENGTHS, model.lower())
    assert hit is not None
    return hit[1]


@pytest.mark.parametrize("key", ORG_KEYS)
def test_org_qualified_key_resolves_to_its_own_value(key):
    assert _resolve(key) == DEFAULT_CONTEXT_LENGTHS[key]


def test_small_window_model_is_not_given_the_family_catch_all():
    assert _resolve("deepseek-ai/DeepSeek-V3.2") == 65536


def test_org_qualified_key_does_not_capture_a_longer_model_id():
    assert _resolve("zai-org/GLM-5.3") == DEFAULT_CONTEXT_LENGTHS["glm-5.3"]
    assert _resolve("deepseek-ai/DeepSeek-V3.2-fast") == DEFAULT_CONTEXT_LENGTHS["deepseek"]
