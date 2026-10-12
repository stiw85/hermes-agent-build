"""Rotation after a credential-wide failure honours the caller's model.

A sibling credential that is only cooled down for a DIFFERENT model is healthy for the model the
caller is serving; rotating without the model treated it as unavailable and reported no recovery.
Real ``agent.credential_pool`` against a real temp auth store.
"""
import json
import time

import pytest

KEY_A = "sk-ant-api03-synthetic-test-key-aaaa"
KEY_B = "sk-ant-api03-synthetic-test-key-bbbb"
OPUS = "claude-opus-4-8"
HAIKU = "claude-haiku-4-5"


@pytest.fixture
def pool(tmp_path, monkeypatch):
    root = tmp_path / "hermes-root"
    root.mkdir()
    (tmp_path / "fakehome").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fakehome"))
    for var in ("ANTHROPIC_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(root))
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    (root / "auth.json").write_text(json.dumps({"credential_pool": {"anthropic": [
        {"id": "a", "label": "a", "auth_type": "api_key", "priority": 0, "source": "manual", "access_token": KEY_A},
        {"id": "b", "label": "b", "auth_type": "api_key", "priority": 1, "source": "manual", "access_token": KEY_B},
    ]}}))
    from agent.credential_pool import load_pool
    return load_pool("anthropic")


def _cool_b_down_for_opus(pool):
    pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint=KEY_B, credential_id="b", failure_reason="rate_limit", model=OPUS,
        error_context={"reset_at": time.time() + 3600},
    )
    assert pool.select(model=HAIKU) is not None  # b's cooldown is opus-only


def test_credential_wide_failure_rotates_to_sibling_cooled_for_another_model(pool):
    _cool_b_down_for_opus(pool)
    rotated = pool.mark_exhausted_and_rotate(
        status_code=401, api_key_hint=KEY_A, credential_id="a", model=HAIKU,
    )
    assert rotated is not None and rotated.id == "b"


def test_unmatched_identity_rotation_also_honours_the_model(pool):
    _cool_b_down_for_opus(pool)
    # Bench a for opus too, so only the model-aware view (haiku) has anything to rotate across.
    pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint=KEY_A, credential_id="a", failure_reason="rate_limit", model=OPUS,
        error_context={"reset_at": time.time() + 3600},
    )
    rotated = pool.mark_exhausted_and_rotate(
        status_code=401, api_key_hint="sk-ant-api03-not-in-the-pool", model=HAIKU,
    )
    assert rotated is not None


def test_rotation_still_skips_a_sibling_cooled_for_the_same_model(pool):
    _cool_b_down_for_opus(pool)
    assert pool.mark_exhausted_and_rotate(
        status_code=401, api_key_hint=KEY_A, credential_id="a", model=OPUS,
    ) is None
