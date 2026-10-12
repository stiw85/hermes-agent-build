"""Redefining a runtime toolset takes effect for it and for every toolset that includes it."""

import pytest

import toolsets
from toolsets import create_custom_toolset, get_toolset_info, resolve_toolset


@pytest.fixture()
def scratch_toolsets():
    names = ("zz_redef_base", "zz_redef_combo")
    yield names
    for name in names:
        toolsets.TOOLSETS.pop(name, None)
    toolsets._resolve_toolset_memo.clear()


def test_redefined_toolset_resolves_to_its_new_tools(scratch_toolsets):
    base, combo = scratch_toolsets
    create_custom_toolset(base, "base", tools=["web_search"])
    create_custom_toolset(combo, "combo", tools=["terminal"], includes=[base])
    assert resolve_toolset(base) == ["web_search"]
    assert resolve_toolset(combo) == ["terminal", "web_search"]

    create_custom_toolset(base, "base", tools=["read_file"])

    assert resolve_toolset(base) == ["read_file"]
    assert resolve_toolset(combo) == ["read_file", "terminal"]
    info = get_toolset_info(base)
    assert info["direct_tools"] == info["resolved_tools"] == ["read_file"]
