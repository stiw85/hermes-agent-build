"""``hermes config set`` on a list index that does not exist.

Lists are never grown by ``config set``; a missing or non-numeric index is a user error that
must end in a one-line refusal with the file untouched, not a traceback.
"""

import pytest

from hermes_cli.config import set_config_value

ORIGINAL = "custom_providers:\n- name: a\n  base_url: http://localhost:1/v1\n"


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(ORIGINAL, encoding="utf-8")
    return path


@pytest.mark.parametrize("key,value", [
    ("custom_providers.5.name", "x"),          # out of range, mid-path
    ("custom_providers.3", "{name: b}"),       # out of range, leaf
    ("custom_providers.first.name", "x"),      # not a number, mid-path
    ("custom_providers.first", "{name: b}"),   # not a number, leaf
])
def test_bad_list_index_is_refused_cleanly(config_path, capsys, key, value):
    with pytest.raises(SystemExit) as exc:
        set_config_value(key, value)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert key in err and "index" in err
    assert "invalid literal" not in err
    assert config_path.read_text(encoding="utf-8") == ORIGINAL


def test_existing_index_still_writes(config_path):
    set_config_value("custom_providers.0.name", "renamed")

    assert "name: renamed" in config_path.read_text(encoding="utf-8")
