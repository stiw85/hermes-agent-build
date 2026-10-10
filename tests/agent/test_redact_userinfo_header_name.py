"""A header-shaped name in URL userinfo masks the token and keeps the remote."""

from agent.redact import redact_sensitive_text


def test_x_access_token_clone_url_keeps_host_and_repo():
    token = "ghs_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    line = f"origin  https://x-access-token:{token}@github.com/acme/widgets.git (fetch)"
    redacted = redact_sensitive_text(line, force=True)
    assert token not in redacted
    assert redacted.endswith("@github.com/acme/widgets.git (fetch)")


def test_prefixless_token_in_userinfo_is_masked_and_remote_kept():
    token = "abcdef0123456789abcdef"
    redacted = redact_sensitive_text(f"https://x-access-token:{token}@github.com/acme/widgets.git", force=True)
    assert token not in redacted
    assert redacted.endswith("@github.com/acme/widgets.git")


def test_secret_header_value_is_still_masked():
    assert "ghijklmnopqrstuv" not in redact_sensitive_text("curl -H x-api-key: abcdefghijklmnopqrstuvwxyz https://api", force=True, code_file=True)
