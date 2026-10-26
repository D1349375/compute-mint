from decimal import Decimal

from billflow.invoice import Invoice, Line


def make(n, price="0.10"):
    return Invoice("INV-1", "c-000", [Line(f"item {i}", Decimal("1"), Decimal(price)) for i in range(n)])


def test_subtotal_adds_line_amounts():
    assert make(3).subtotal() == Decimal("0.30")


def test_tax_is_rounded_once_on_the_subtotal():
    # ten lines of 0.10 add up to 1.00; 5% of that is 0.05, not ten roundings of 0.005
    assert make(10).tax() == Decimal("0.05")


def test_total():
    inv = make(2, price="100.00")
    assert inv.total() == Decimal("210.00")
