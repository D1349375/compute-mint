"""The nightly bill run: one invoice per client."""
from datetime import date
from decimal import Decimal

from .duedates import due_date
from .invoice import Invoice, Line


def run_for_client(client: dict, usage: list[tuple[str, Decimal, Decimal]], issued: date, seq: int) -> tuple[Invoice, date]:
    """Build the invoice for ``client`` from ``(description, quantity, unit_price)`` usage rows
    and return it with its due date."""
    currency = client["currency"]
    invoice = Invoice(
        number=f"INV-{issued.year}-{seq:04d}",
        client_id=client["id"],
        lines=[Line(*row) for row in usage],
        currency=currency,
    )
    return invoice, due_date(issued, client["terms"])
