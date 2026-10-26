import pytest

from shared.wrapping import wrap_words


def test_greedy_wrap():
    assert wrap_words("the quick brown fox jumps", 10) == ["the quick", "brown fox", "jumps"]


def test_long_word_gets_its_own_line():
    assert wrap_words("a extraordinarily b", 5) == ["a", "extraordinarily", "b"]


def test_empty_text():
    assert wrap_words("", 10) == []


def test_extra_whitespace_is_collapsed():
    assert wrap_words("a   b\n c", 10) == ["a b c"]


def test_width_must_be_positive():
    with pytest.raises(ValueError):
        wrap_words("x", 0)
