from datetime import date
from decimal import Decimal

from billflow.billrun import run_for_client


def test_invoice_number_and_due_date(clients):
    usage = [("seats", Decimal("2"), Decimal("50.00"))]
    invoice, due = run_for_client(clients[0], usage, date(2026, 1, 15), 7)
    assert invoice.number == "INV-2026-0007"
    assert due == date(2026, 2, 14)
