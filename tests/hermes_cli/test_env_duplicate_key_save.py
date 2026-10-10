"""``save_env_value`` on a ``.env`` that defines the key more than once.

Every reader (``load_env`` and python-dotenv at startup) honours the LAST assignment, so the
save must land there and leave no older duplicate behind to shadow it or resurrect later.
"""

import pytest

from hermes_cli.config import invalidate_env_cache, load_env, save_env_value


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    invalidate_env_cache()
    return tmp_path / ".env"


def test_saved_value_wins_over_existing_duplicates(env_file):
    env_file.write_text("EXAMPLE_SETTING=old-first\nOTHER=1\nEXAMPLE_SETTING=old-last\n", encoding="utf-8")

    save_env_value("EXAMPLE_SETTING", "new-value")

    assert load_env()["EXAMPLE_SETTING"] == "new-value"


def test_save_collapses_duplicates_and_keeps_other_lines(env_file):
    env_file.write_text(
        "# header\nexport EXAMPLE_SETTING=a\nOTHER=1\nEXAMPLE_SETTING = b\nLAST=2\n", encoding="utf-8")

    save_env_value("EXAMPLE_SETTING", "c")

    assert env_file.read_text(encoding="utf-8") == "# header\nOTHER=1\nEXAMPLE_SETTING=c\nLAST=2\n"
