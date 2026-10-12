"""An orphan think close tag is dropped from streamed text however the deltas are cut."""

from unittest.mock import MagicMock

import pytest

from gateway.stream_consumer import GatewayStreamConsumer


def _stream(deltas: list[str]) -> str:
    consumer = GatewayStreamConsumer(MagicMock(), "chat_test")
    for delta in deltas:
        consumer._filter_and_accumulate(delta)
    consumer._flush_think_buffer()
    return consumer._accumulated


@pytest.mark.parametrize("deltas", [
    ["let me check.", "</", "think", ">", "\n\nThe answer is 42."],
    ["let me check.</thi", "nk>\n\nThe answer is 42."],
    ["let me check.<", "/think>\n\nThe answer is 42."],
])
def test_orphan_close_tag_split_across_deltas_is_stripped(deltas):
    # Whitespace after the tag may arrive in a later delta, so compare the non-space text.
    assert "".join(_stream(deltas).split()) == "letmecheck.Theansweris42."


def test_text_that_only_resembles_a_close_tag_is_delivered():
    assert _stream(["a </", "b> c"]) == "a </b> c"
    assert _stream(["ends with </"]) == "ends with </"
