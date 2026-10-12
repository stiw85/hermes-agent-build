"""A hand-edited ``agent:`` holding a scalar or list must not take the whole config loader down.

Every other section tolerates the same typo; ``agent`` crashed in the max_turns normalisation,
so ``hermes config check`` (the command that should diagnose it) died with a traceback.
"""

import pytest

from hermes_cli.config import load_config, resolve_turn_limit, validate_config_structure


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path / "config.yaml"


@pytest.mark.parametrize("agent_value", ["5", "fast", "[a, b]", "true"])
def test_non_mapping_agent_section_loads(config_path, agent_value):
    config_path.write_text(f"agent: {agent_value}\nterminal:\n  backend: docker\n", encoding="utf-8")

    cfg = load_config()

    assert isinstance(cfg["agent"], dict)
    assert cfg["terminal"]["backend"] == "docker"
    assert all("Could not load" not in issue.message for issue in validate_config_structure())


def test_root_max_turns_still_relocates_beside_a_non_mapping_agent(config_path):
    config_path.write_text("max_turns: 12\nagent: 5\n", encoding="utf-8")

    cfg = load_config()

    assert resolve_turn_limit(cfg["agent"]["max_turns"]) == 12
