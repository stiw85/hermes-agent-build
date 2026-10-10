"""Unit and currency expansion keys on the written form: ``5m`` is metres, ``5M`` is five
million; ``CA$`` is Canadian, never "C" plus Australian dollars."""

import pytest

from tools.tts_text_normalize import prepare_spoken_text


@pytest.mark.parametrize("text", [
    "They raised $5M last year.",
    "The app has 20M users.",
    "A 3 MM round closed.",
    "Storage grew to 40 CM units.",
])
def test_uppercase_magnitude_suffix_is_not_a_length(text):
    spoken = prepare_spoken_text(text)
    assert "metres" not in spoken, spoken


def test_money_magnitude_suffix_is_spoken_before_the_currency():
    spoken = prepare_spoken_text("They raised $5M, then US$3B, on $20K of revenue; a $2.5MM round and $300, flat.")
    assert "5 million dollars" in spoken
    assert "3 billion US dollars" in spoken
    assert "20 thousand dollars" in spoken
    assert "2.5 million dollars" in spoken
    assert "300 dollars," in spoken


def test_lowercase_length_units_still_expand():
    spoken = prepare_spoken_text("Run 100 m, then 3 mm of rain, 12 cm of snow and 9 km/h or 9 KM/H wind.")
    assert "100 metres" in spoken
    assert "3 millimetres" in spoken
    assert "12 centimetres" in spoken
    assert spoken.count("9 kilometres per hour") == 2


def test_canadian_dollars_are_not_australian():
    spoken = prepare_spoken_text("It costs CA$50 or C$5, versus A$60.")
    assert "50 Canadian dollars" in spoken
    assert "5 Canadian dollars" in spoken
    assert "60 Australian dollars" in spoken
    assert "C50" not in spoken and spoken.count("Australian") == 1
