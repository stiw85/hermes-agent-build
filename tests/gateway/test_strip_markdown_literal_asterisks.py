"""strip_markdown removes emphasis markers but keeps literal asterisks and code content."""

import pytest

from gateway.platforms.helpers import strip_markdown


@pytest.mark.parametrize("text", [
    "Total: 2 * 3 * 4 = 24",
    "Area is 2*3*4 units",
    "Options:\n* first item\n* second item\n* third item",
    "Rating: 5* hotel vs 4* hotel",
])
def test_literal_asterisks_are_kept(text):
    assert strip_markdown(text) == text


def test_emphasis_is_still_stripped():
    assert strip_markdown("**bold** and *italic* and ***both*** and __b__ and _i_") == "bold and italic and both and b and i"
    assert strip_markdown("* **Label**: *value*") == "* Label: value"


def test_fenced_code_content_is_verbatim():
    code = "area = w * h * 2\ndef __init__(self, *args, **kwargs): pass\nsee [x](y)"
    assert strip_markdown(f"Before\n```python\n{code}\n```\nAfter **bold**") == f"Before\n{code}\nAfter bold"


def test_inline_code_content_is_verbatim():
    assert strip_markdown("Run `rm *.log` then `ls *.txt` or `x.__init__()`") == "Run rm *.log then ls *.txt or x.__init__()"
