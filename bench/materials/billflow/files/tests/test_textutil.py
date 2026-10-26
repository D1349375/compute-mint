import pytest

from shared.textutil import chunked, initials


def test_chunked_even():
    assert chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunked_keeps_the_short_last_chunk():
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunked_rejects_zero():
    with pytest.raises(ValueError):
        chunked([1], 0)


def test_initials():
    assert initials("ada king lovelace") == "AKL"
