from decimal import Decimal

import pytest

from billflow.money import split_amount, to_money


def test_to_money_rounds_half_even():
    assert to_money("2.675") == Decimal("2.68")
    assert to_money("2.665") == Decimal("2.66")


def test_split_even():
    assert split_amount(Decimal("90.00"), 3) == [Decimal("30.00")] * 3


def test_split_gives_extra_cents_to_the_first_shares():
    shares = split_amount(Decimal("100.00"), 3)
    assert shares == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert sum(shares) == Decimal("100.00")


def test_split_needs_at_least_one_part():
    with pytest.raises(ValueError):
        split_amount(Decimal("1.00"), 0)
