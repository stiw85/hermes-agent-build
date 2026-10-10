"""The foreground guard refuses commands that START a server or background a job — not ones
that mention a server's name or carry ``&`` inside a quoted argument."""

import pytest

from tools.terminal_tool import _foreground_background_guidance


@pytest.mark.parametrize("command", [
    "pip install uvicorn gunicorn",
    "grep -c uvicorn requirements.txt",
    "ps aux | grep gunicorn",
    "npm install -D nodemon vite",
    "pkill -f uvicorn",
    "which gunicorn",
    "cat vite.config.ts && ls vite",
    "echo nodemon is listed in package.json",
])
def test_naming_a_server_is_not_starting_it(command):
    assert _foreground_background_guidance(command) is None


@pytest.mark.parametrize("command", [
    "uvicorn app:app --reload",
    "cd api && uvicorn main:app",
    "PORT=8000 gunicorn -w 4 app:app",
    "python -m uvicorn app:app",
    "source .venv/bin/activate; gunicorn app:app",
    ".venv/bin/uvicorn app:app",
    "npx vite",
    "vite",
    "nodemon server.js",
    "npx nodemon server.js",
    "npm run dev",
])
def test_starting_a_server_in_the_foreground_is_still_refused(command):
    msg = _foreground_background_guidance(command)
    assert msg is not None and "long-lived" in msg


@pytest.mark.parametrize("command", [
    '''gh pr create --title "Fix user's bug" --body 'Details' --label "R & D"''',
    '''echo "a's" 'b' "c & d"''',
    """echo 'say "hi" & wave' "it's fine\"""",
])
def test_ampersand_inside_quotes_survives_a_mixed_quote_command(command):
    assert _foreground_background_guidance(command) is None


@pytest.mark.parametrize("command", [
    '''echo "it's" & sleep 60''',
    """python3 server.py --name 'x' &""",
])
def test_real_backgrounding_next_to_quotes_is_still_refused(command):
    msg = _foreground_background_guidance(command)
    assert msg is not None and "WITHOUT the '&'" in msg
