"""Operating-discipline guidance reaches every session's stable prompt, whatever the persona."""
from types import SimpleNamespace
from unittest.mock import patch

from agent.prompt_builder import OPERATING_DISCIPLINE_GUIDANCE
from agent.system_prompt import build_system_prompt_parts


def _agent(**overrides):
    base = dict(
        load_soul_identity=False,
        skip_context_files=False,
        valid_tool_names=[],
        _task_completion_guidance=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=None,
        _memory_manager=None,
        model="",
        provider="",
        platform="",
        pass_session_id=False,
        session_id="",
        _emit_status=lambda *_args, **_kwargs: None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _parts(agent, soul=""):
    with (
        patch("agent.prompt_builder.load_soul_md", return_value=soul),
        patch("agent.prompt_builder.build_environment_hints", return_value=""),
        patch("agent.prompt_builder.build_context_files_prompt", return_value=""),
    ):
        return build_system_prompt_parts(agent)


def test_guidance_is_in_stable_prefix_without_a_persona():
    assert OPERATING_DISCIPLINE_GUIDANCE in _parts(_agent())["stable"]


def test_guidance_still_applies_when_user_has_a_custom_persona():
    parts = _parts(_agent(), soul="You are a terse pirate.")
    assert "terse pirate" in parts["stable"]
    assert OPERATING_DISCIPLINE_GUIDANCE in parts["stable"]
