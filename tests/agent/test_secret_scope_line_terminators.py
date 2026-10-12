"""The ``.env`` tokenizer splits lines exactly where the writers and python-dotenv do.

``str.splitlines()`` also breaks on form feed, vertical tab, the FS/GS/RS separators, NEL and
U+2028/U+2029. Those are value data everywhere else (``save_env_value`` strips only CR/LF and
python-dotenv, which fills ``os.environ``, splits only on them), so splitting there truncates
the value and turns its tail into a second assignment.
"""

import pytest

from agent.secret_scope import load_env_file


@pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", " ", " "])
def test_in_value_separator_is_not_a_line_break(tmp_path, separator):
    env = tmp_path / ".env"
    env.write_text(f'NOTE="first{separator}SECOND_NAME=tail"\nNEXT=1\n', encoding="utf-8")

    assert load_env_file(env) == {"NOTE": f"first{separator}SECOND_NAME=tail", "NEXT": "1"}


def test_latin1_nel_byte_stays_inside_the_value(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"PHRASE=caf\xe9\x85tail\nNEXT=1\n")  # invalid UTF-8 -> latin-1; 0x85 is NEL

    assert load_env_file(env) == {"PHRASE": "caf\xe9\x85tail", "NEXT": "1"}


def test_lf_crlf_and_bare_cr_still_separate_assignments(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"A=1\nB=2\r\nC=3\rD=4")

    assert load_env_file(env) == {"A": "1", "B": "2", "C": "3", "D": "4"}
