"""The fence around tool output is longer than any backtick run inside it."""

from __future__ import annotations

import re

import pytest

from acp_adapter.tools import _fenced_text


@pytest.mark.parametrize("text", [
    "plain", "it`s\n```\ncode\n```", "````\nx\n````", "``` ```", "`a` then ``b`` then ```", "`" * 9,
])
def test_fence_outruns_every_backtick_run(text):
    fenced = _fenced_text(text, "md")
    fence = fenced.split("md\n", 1)[0]

    assert set(fence) == {"`"} and len(fence) >= 3
    assert len(fence) > max((len(run) for run in re.findall(r"`+", text)), default=0)
    assert fenced == f"{fence}md\n{text}\n{fence}"


def test_fence_length_ignores_the_text_between_backticks():
    assert _fenced_text("`a_rather_long_identifier_name`").startswith("```\n")
