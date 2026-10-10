"""replace_all through a line-window strategy must use non-overlapping matches.

The exact strategy already has ``str.replace`` semantics; the whitespace-tolerant
line strategies have to agree, because overlapping spans cannot be spliced.
"""

from tools.fuzzy_match import _strategy_line_trimmed, fuzzy_find_and_replace


def test_repeated_lines_replace_like_str_replace():
    content = "calls:\n    step()\n    step()\n    step()\nend\n"

    new, count, strategy, err = fuzzy_find_and_replace(
        content, "step()\nstep()", "step(2)", replace_all=True)

    assert err is None
    assert strategy == "line_trimmed"
    assert count == 1
    assert new == "calls:\n    step(2)\n    step()\nend\n"


def test_text_after_overlapping_windows_survives():
    content = "    x\n    x\n    x\n    x\ntail_line_that_must_survive\n"

    new, count, _strategy, err = fuzzy_find_and_replace(content, "x\nx\nx", "REPLACED", replace_all=True)

    assert err is None
    assert count == 1
    assert new == "    REPLACED\n    x\ntail_line_that_must_survive\n"


def test_line_window_spans_never_overlap():
    spans = _strategy_line_trimmed("  a\n  a\n  a\n  a\n  a\n", "a\na")

    assert all(prev_end <= start for (_s, prev_end), (start, _e) in zip(spans, spans[1:]))
    assert len(spans) == 2
