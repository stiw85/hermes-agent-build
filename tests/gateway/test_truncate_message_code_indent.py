"""truncate_message keeps code intact across chunk boundaries and every chunk within the limit."""

import re

from gateway.platforms.base import BasePlatformAdapter

_INDICATOR = re.compile(r" \(\d+/\d+\)$")


def _code_bodies(chunks: list[str], lang: str) -> str:
    """Rejoin the fenced code of every chunk the way a reader would paste it back together."""
    bodies = []
    for chunk in chunks:
        match = re.search(rf"```{lang}\n(.*?)\n```", _INDICATOR.sub("", chunk), re.DOTALL)
        assert match, chunk[:80]
        bodies.append(match.group(1))
    return "\n".join(bodies)


def test_indentation_survives_a_split_inside_a_code_block():
    lines = ["def handler(event):"]
    for i in range(120):
        lines += [f"    if event.kind == {i}:", f"        return handle_{i}(event)"]
    code = "\n".join(lines)
    chunks = BasePlatformAdapter.truncate_message(f"```python\n{code}\n```", 4096)
    assert len(chunks) > 1
    assert _code_bodies(chunks, "python") == code
    compile(_code_bodies(chunks, "python"), "<chunks>", "exec")


def test_prose_split_still_drops_boundary_whitespace():
    chunks = BasePlatformAdapter.truncate_message("word " * 2000, 4096)
    assert len(chunks) > 1
    assert all(not _INDICATOR.sub("", c).startswith(" ") for c in chunks)


def test_last_chunk_of_an_unclosed_fence_fits_with_two_digit_indicator():
    # Ten chunks, the tail still inside the fence and sized right at the final-chunk budget.
    message = "```js\n" + ("y" * 70 + "\n") * 560 + "z" * 743
    chunks = BasePlatformAdapter.truncate_message(message, 4096)
    assert len(chunks) >= 10
    assert max(len(c) for c in chunks) <= 4096
