from decimal import Decimal

from billflow.notify import reminder_text


def test_mentions_the_invoice_number(clients):
    assert "INV-1" in reminder_text(clients[0], "INV-1", 3, Decimal("10.00"))


def test_plural_days(clients):
    assert "3 days overdue" in reminder_text(clients[0], "INV-1", 3, Decimal("10.00"))


def test_one_day_is_singular(clients):
    assert "1 day overdue" in reminder_text(clients[0], "INV-1", 1, Decimal("10.00"))
