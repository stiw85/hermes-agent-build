"""Saving a config whose file has a bare section key (``terminal:`` with every child commented out).

The bare key parses as YAML null and loads as the default mapping (#58277). A later
load-modify-save must not copy that default mapping into config.yaml: a written default is a
pin that hides future default changes (a pinned sandbox image recreates a persisted container).
"""

import pytest

from hermes_cli.config import DEFAULT_CONFIG, load_config, read_user_config_raw, save_config

BARE_SECTIONS = "model:\n  default: test/custom\nterminal:\n  # backend: docker\ndisplay:\n"


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(BARE_SECTIONS, encoding="utf-8")
    return path


def test_bare_section_does_not_materialise_defaults_on_save(config_path):
    cfg = load_config()
    cfg["model"]["default"] = "test/other"
    save_config(cfg)

    saved = read_user_config_raw(config_path)
    assert saved["model"]["default"] == "test/other"
    assert not saved.get("terminal")
    assert not saved.get("display")
    assert load_config()["terminal"] == DEFAULT_CONFIG["terminal"]


def test_bare_section_line_and_its_comment_survive_the_save(config_path):
    save_config(load_config())

    text = config_path.read_text(encoding="utf-8")
    assert "terminal:\n  # backend: docker\n" in text
    assert "terminal" in read_user_config_raw(config_path)


def test_a_change_inside_a_bare_section_is_still_saved(config_path):
    cfg = load_config()
    cfg["terminal"]["backend"] = "docker"
    save_config(cfg)

    assert read_user_config_raw(config_path)["terminal"] == {"backend": "docker"}
