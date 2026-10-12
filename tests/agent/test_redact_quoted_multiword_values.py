"""A quoted secret value is masked whole, spaces included, with its quotes intact."""

import time

import pytest

from agent.redact import redact_sensitive_text, redact_terminal_output

_PHRASE = "correct horse battery staple"


@pytest.mark.parametrize("template", [
    'SMTP_PASSWORD="{}"',
    "export DB_PASSWORD='{}' # prod",
    'smtp_password="{}"',
    'password="{}"',
    "spring.datasource.password='{}'",
])
def test_quoted_value_with_spaces_is_masked_whole(template):
    line = template.format(_PHRASE)
    # One pass leaves the log mask's head/tail, a second pass over it collapses to ``***``.
    masked = {template.format("***"), template.format("correc...aple")}
    assert redact_sensitive_text(line, force=True) in masked
    assert redact_terminal_output(line, "env", force=True) in masked


@pytest.mark.parametrize("line", [
    'MAX_TOKENS=100',
    'API_KEY="$OPENAI_API_KEY"',
    'a=1&password=hunter2&token=abc',
])
def test_quoted_value_change_keeps_existing_carve_outs(line):
    before = {'a=1&password=hunter2&token=abc': 'a=1&password=***&token=***'}.get(line, line)
    assert redact_sensitive_text(line, force=True) == before


def test_second_assignment_on_the_line_is_not_swallowed():
    line = 'DB_PASSWORD="first phrase" NOTE="keep me"'
    assert redact_sensitive_text(line, force=True) == 'DB_PASSWORD="***" NOTE="keep me"'


def test_long_unterminated_quoted_lines_stay_linear():
    text = "\n".join('DB_PASSWORD="' + "word " * 4000 for _ in range(20)) + "\npassword='" + "x " * 50_000
    start = time.monotonic()
    redact_sensitive_text(text, force=True)
    assert time.monotonic() - start < 5
