"""An indented reasoning block is scrubbed however the stream chunks the indent."""

import pytest

from agent.think_scrubber import StreamingThinkScrubber


def _drive(deltas: list[str]) -> str:
    scrubber = StreamingThinkScrubber()
    return "".join(scrubber.feed(d) for d in deltas) + scrubber.flush()


@pytest.mark.parametrize("deltas, visible", [
    ([" ", "<think>", "secret plan", "</think>", "Answer"], " Answer"),
    (["Intro\n", "  ", "<think>", "secret plan", "</think>", "Answer"], "Intro\n  Answer"),
    (["Intro\n", " ", " ", "<think>", "secret plan"], "Intro\n  "),
])
def test_whitespace_only_delta_before_open_tag_keeps_the_block_boundary(deltas, visible):
    assert _drive(deltas) == visible
    assert _drive(["".join(deltas)]) == visible


def test_mid_line_mention_split_across_deltas_is_still_prose():
    assert _drive(["Use the ", "<think>", " tag\n"]) == "Use the <think> tag\n"
    assert _drive(["word", " ", "<think>", " tag"]) == "word <think> tag"
