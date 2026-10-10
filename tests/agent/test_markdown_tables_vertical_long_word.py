"""The vertical fallback breaks an over-wide word across lines without adding characters."""

from wcwidth import wcswidth

from agent.markdown_tables import realign_markdown_tables


def test_hard_broken_url_rejoins_to_the_original():
    url = "https://example.com/" + "a" * 88 + "/b"
    src = f"| Name | A very long header label x |\n|---|---|\n| x | {url} |"
    lines = realign_markdown_tables(src, available_width=40).split("\n")
    assert lines[0] == "Name: x"
    assert "".join(line.strip() for line in lines[1:]) == f"A very long header label x: {url}"
    assert all(wcswidth(line) <= 40 for line in lines)


def test_prose_after_a_long_word_still_wraps_at_spaces():
    src = "| K | A long header label here |\n|---|---|\n| x | " + "b" * 30 + " then some ordinary words follow |"
    lines = realign_markdown_tables(src, available_width=40).split("\n")
    body = " ".join(line.strip() for line in lines[1:])
    assert "then some ordinary words follow" in body
