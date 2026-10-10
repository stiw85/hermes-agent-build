"""Vendor credential shapes the prefix and URL passes must mask in full."""

import pytest

from agent.redact import redact_sensitive_text, redact_terminal_output

_SENDGRID = "SG." + "aBcDeFgHiJkLmNoPqRsTuV" + "." + "0123456789abcdefghijABCDEFGHIJ0123456789xyz"
_PASSWORD = "s3cr3tPassw0rd"


@pytest.mark.parametrize("text", [f"key is {_SENDGRID}.", f"SENDGRID={_SENDGRID}", f"{_SENDGRID}\n"])
def test_sendgrid_secret_segment_is_masked(text):
    for redacted in (redact_sensitive_text(text, force=True), redact_terminal_output(text, "cat notes.txt", force=True)):
        assert _SENDGRID.rsplit(".", 1)[1] not in redacted


def test_sendgrid_mask_stops_at_sentence_punctuation():
    assert redact_sensitive_text(f"rotate {_SENDGRID}. Then deploy.", force=True).endswith(". Then deploy.")


@pytest.mark.parametrize("url", [
    f"redis://:{_PASSWORD}@cache.internal:6379/0",
    f"rediss://:{_PASSWORD}@cache:6380",
    f"amqp://:{_PASSWORD}@mq:5672",
    f"amqps://worker:{_PASSWORD}@mq",
    f"postgresql+asyncpg://app:{_PASSWORD}@db/app",
    f"postgresql+psycopg2://app:{_PASSWORD}@db:5432/app",
    f"mariadb://app:{_PASSWORD}@db/app",
    f"mssql+pyodbc://app:{_PASSWORD}@db/app",
])
def test_connection_string_password_is_masked(url):
    scheme_and_user, _, host = url.partition(_PASSWORD)
    for redacted in (redact_sensitive_text(url, force=True), redact_terminal_output(url, "cat settings.py", force=True)):
        assert redacted == f"{scheme_and_user}***{host}"


@pytest.mark.parametrize("text", [
    "redis://localhost:6379/0 owner ops@example.com",
    "see redis://cache:6379 and mail a:b@example.com",
])
def test_passwordless_connection_string_is_left_alone(text):
    assert redact_sensitive_text(text, force=True) == text


def test_fstring_connection_template_survives_in_source():
    template = 'f"postgresql+asyncpg://{user}:{password}@{host}/{name}"'
    assert redact_sensitive_text(template, force=True, code_file=True) == template
