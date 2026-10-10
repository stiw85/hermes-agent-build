"""A whitespace-normalized match starts at the matched text, not inside the run of
spaces before it: swallowed padding is otherwise taken for the file's indentation
and prefixed to every line of a multi-line replacement."""

from tools.fuzzy_match import _strategy_whitespace_normalized, fuzzy_find_and_replace


def test_span_starts_at_first_matched_character():
    assert _strategy_whitespace_normalized("a   b   c\n", "b c") == [(4, 9)]
    assert _strategy_whitespace_normalized("x\n\t\t  a  = 1\n", "a = 1") == [(6, 12)]


def test_multiline_replacement_after_alignment_padding_keeps_columns():
    content = "foo = 1      # first\nbarbaz = 2   # second\n"

    new, count, strategy, err = fuzzy_find_and_replace(
        content, "# first\nbarbaz = 2 # second", "# FIRST\nbarbaz = 2 # second")

    assert err is None and count == 1
    assert strategy == "whitespace_normalized"
    assert new == "foo = 1      # FIRST\nbarbaz = 2 # second\n"


def test_leading_space_in_pattern_still_absorbs_the_whole_run():
    new, count, _strategy, err = fuzzy_find_and_replace("a   b   c\n", "a b", "X")

    assert err is None and count == 1
    assert new == "X   c\n"
