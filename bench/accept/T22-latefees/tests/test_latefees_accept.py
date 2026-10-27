from decimal import Decimal

from billflow.latefees import late_fee


def test_fee_grows_with_days():
    assert late_fee(Decimal("1000.00"), 10) == Decimal("5.00")


def test_nothing_due_for_zero_or_negative_days():
    assert late_fee(Decimal("1000.00"), 0) == Decimal("0.00")
    assert late_fee(Decimal("1000.00"), -3) == Decimal("0.00")


def test_fee_is_capped():
    assert late_fee(Decimal("1000.00"), 1000) == Decimal("150.00")


def test_custom_rate_and_cap():
    assert late_fee(Decimal("200.00"), 4, daily_rate=Decimal("0.01"), cap=Decimal("0.03")) == Decimal("6.00")


def test_result_has_two_places():
    assert late_fee(Decimal("333.33"), 7) == Decimal("1.17")
