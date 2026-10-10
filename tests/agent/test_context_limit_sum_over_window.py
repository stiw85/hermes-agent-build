"""Anthropic's "input length and `max_tokens` exceed context limit: A + B > C" 400.

A is the measured input, B the requested output cap and C the real window: the input fits, so the
recovery is a smaller ``max_tokens`` (C - A), and the only window the message reports is C. Reading
A as the window shrank (and persisted) the context length to whatever the prompt size happened to be.
"""

from agent.model_metadata import (
    get_context_length_from_provider_error,
    is_output_cap_error,
    parse_available_output_tokens_from_error,
    parse_context_limit_from_error,
)

FITS = (
    "input length and `max_tokens` exceed context limit: 188240 + 21333 > 200000, "
    "decrease input length or `max_tokens` and try again"
)
INPUT_ALONE_OVERFLOWS = (
    "input length and `max_tokens` exceed context limit: 250000 + 8192 > 200000, "
    "decrease input length or `max_tokens` and try again"
)


def test_fitting_input_is_an_output_cap_error_with_the_remaining_budget():
    assert parse_available_output_tokens_from_error(FITS) == 200000 - 188240
    assert is_output_cap_error(FITS)


def test_reported_window_is_the_right_hand_side_never_the_input_size():
    assert parse_context_limit_from_error(FITS) == 200000
    # The window Hermes already assumes is confirmed, not replaced by the prompt size.
    assert get_context_length_from_provider_error(FITS, 200000) is None
    # A 1M-assumed model on a 200K route learns the real window.
    assert get_context_length_from_provider_error(FITS, 1_000_000) == 200000


def test_input_that_alone_overflows_stays_a_context_overflow():
    assert parse_available_output_tokens_from_error(INPUT_ALONE_OVERFLOWS) is None
    assert not is_output_cap_error(INPUT_ALONE_OVERFLOWS)
    assert parse_context_limit_from_error(INPUT_ALONE_OVERFLOWS) == 200000
