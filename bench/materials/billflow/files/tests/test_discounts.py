from decimal import Decimal

from billflow.discounts import client_discount, volume_discount

TIERS = [{"min": 0, "rate": 0}, {"min": 10000, "rate": 0.03}, {"min": 50000, "rate": 0.06}]


def test_below_the_first_paid_tier():
    assert volume_discount(Decimal("9999.99"), TIERS) == Decimal("0")


def test_reaching_a_tier_exactly_earns_its_rate():
    assert volume_discount(Decimal("10000"), TIERS) == Decimal("0.03")


def test_above_the_top_tier():
    assert volume_discount(Decimal("75000"), TIERS) == Decimal("0.06")


def test_client_extra_is_added_and_capped():
    rates = {"tiers": TIERS, "max_total": 0.08, "clients": {"x": {"extra": 0.05}}}
    assert client_discount("x", Decimal("60000"), rates) == Decimal("0.08")
