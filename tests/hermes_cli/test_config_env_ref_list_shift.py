"""``${VAR}`` templates in list items survive a save that shifts the list.

Saving a loaded (expanded) config must never write a referenced secret back in plaintext. Items
without a unique ``name`` (fallback entries, argument lists) cannot be matched by name, so
removing or inserting an earlier item must not misalign the rest with the wrong raw template.
"""

import pytest

from hermes_cli.config import load_config, read_user_config_raw, save_config

VALUE_A = "value-for-a"
VALUE_B = "value-for-b"


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("EXAMPLE_KEY_A", VALUE_A)
    monkeypatch.setenv("EXAMPLE_KEY_B", VALUE_B)
    return tmp_path / "config.yaml"


def test_removing_an_earlier_entry_keeps_the_later_entrys_template(config_path):
    config_path.write_text(
        "fallback_providers:\n"
        "- provider: custom\n  model: model-a\n  base_url: https://a.example/v1\n  api_key: ${EXAMPLE_KEY_A}\n"
        "- provider: custom\n  model: model-b\n  base_url: https://b.example/v1\n  api_key: ${EXAMPLE_KEY_B}\n",
        encoding="utf-8")

    cfg = load_config()
    assert cfg["fallback_providers"][1]["api_key"] == VALUE_B
    cfg["fallback_providers"].pop(0)
    save_config(cfg)

    assert VALUE_B not in config_path.read_text(encoding="utf-8")
    saved = read_user_config_raw(config_path)["fallback_providers"]
    assert [entry["model"] for entry in saved] == ["model-b"]
    assert saved[0]["api_key"] == "${EXAMPLE_KEY_B}"


def test_inserting_before_a_templated_string_keeps_its_template(config_path):
    config_path.write_text(
        "mcp_servers:\n  example:\n    command: example-server\n"
        "    args: ['--token', '${EXAMPLE_KEY_A}']\n",
        encoding="utf-8")

    cfg = load_config()
    cfg["mcp_servers"]["example"]["args"].insert(0, "--verbose")
    save_config(cfg)

    assert VALUE_A not in config_path.read_text(encoding="utf-8")
    assert read_user_config_raw(config_path)["mcp_servers"]["example"]["args"] == [
        "--verbose", "--token", "${EXAMPLE_KEY_A}"]
