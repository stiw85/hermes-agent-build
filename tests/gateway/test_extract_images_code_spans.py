"""extract_images leaves image markup inside code alone: it is an example, not an attachment."""

from gateway.platforms.base import BasePlatformAdapter


def test_markdown_image_in_fenced_code_is_not_extracted():
    text = "To embed a logo write:\n```markdown\n![logo](https://example.com/logo.png)\n```\nThat's it."
    assert BasePlatformAdapter.extract_images(text) == ([], text)


def test_image_tags_in_inline_code_are_not_extracted():
    text = 'Use `![logo](https://example.com/logo.png)` or `<img src="https://example.com/a.png">`.'
    assert BasePlatformAdapter.extract_images(text) == ([], text)


def test_image_outside_code_is_extracted_and_the_code_copy_survives():
    text = "![chart](https://example.com/chart.png)\n\nSource: `![chart](https://example.com/chart.png)`"
    images, cleaned = BasePlatformAdapter.extract_images(text)
    assert images == [("https://example.com/chart.png", "chart")]
    assert cleaned == "Source: `![chart](https://example.com/chart.png)`"


def test_markdown_then_html_images_keep_their_order():
    text = '<img src="https://example.com/b.png"> then ![a](https://example.com/a.png) and ![doc](https://example.com/x.pdf)'
    images, cleaned = BasePlatformAdapter.extract_images(text)
    assert images == [("https://example.com/a.png", "a"), ("https://example.com/b.png", "")]
    assert cleaned == "then  and ![doc](https://example.com/x.pdf)"
