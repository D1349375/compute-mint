import pytest

from slugkit.textutil import truncate


def test_short_text_is_unchanged():
    assert truncate("hello", 10) == "hello"
    assert truncate("hello", 5) == "hello"


def test_long_text_is_cut_to_exactly_width_including_the_suffix():
    out = truncate("hello world", 8)
    assert out == "hello..."
    assert len(out) == 8


def test_custom_suffix():
    assert truncate("abcdefghij", 6, suffix="~") == "abcde~"


def test_width_smaller_than_suffix_raises():
    with pytest.raises(ValueError):
        truncate("abcdef", 2)
