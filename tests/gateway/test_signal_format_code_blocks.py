"""Signal formatting keeps code verbatim and its MONOSPACE range on the code."""

from gateway.platforms.signal_format import markdown_to_signal


def _covered(text: str, styles: list[str], style_type: str) -> list[str]:
    """Substrings of ``text`` each ``style_type`` range covers (ranges are UTF-16 units)."""
    raw = text.encode("utf-16-le")
    out = []
    for style in styles:
        start, length, kind = style.split(":")
        if kind == style_type:
            out.append(raw[2 * int(start):2 * (int(start) + int(length))].decode("utf-16-le"))
    return out


def test_comment_line_in_code_block_is_not_a_heading():
    text, styles = markdown_to_signal("```bash\n# install deps\npip install foo\n```")
    assert text == "# install deps\npip install foo"
    assert _covered(text, styles, "MONOSPACE") == [text]
    assert _covered(text, styles, "BOLD") == []


def test_emphasis_markers_inside_code_block_are_literal():
    code = "def __init__(self, *args, **kwargs):\n    find('*.py', '*.txt')"
    text, styles = markdown_to_signal(f"```python\n{code}\n```")
    assert text == code
    assert _covered(text, styles, "MONOSPACE") == [code]
    assert len(styles) == 1


def test_heading_before_code_block_keeps_monospace_on_the_code():
    text, styles = markdown_to_signal("## Setup 😀\nRun this:\n```bash\npip install foo\n```\nThen **done**.")
    assert text == "Setup 😀\nRun this:\npip install foo\nThen done."
    assert _covered(text, styles, "MONOSPACE") == ["pip install foo"]
    assert _covered(text, styles, "BOLD") == ["Setup 😀", "done"]


def test_emphasis_markers_inside_inline_code_are_literal():
    text, styles = markdown_to_signal("Call `obj.__init__()` then `rm *.log` and `ls *.txt`")
    assert text == "Call obj.__init__() then rm *.log and ls *.txt"
    assert _covered(text, styles, "MONOSPACE") == ["obj.__init__()", "rm *.log", "ls *.txt"]
    assert len(styles) == 3
