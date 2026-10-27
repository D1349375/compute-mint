from decimal import Decimal

from billflow.invoice import Invoice, Line
from billflow.serialize import invoice_to_dict


def test_invoice_to_dict():
    inv = Invoice("INV-9", "c-000", [Line("seats", Decimal("2"), Decimal("50.00")),
                                      Line("support", Decimal("1"), Decimal("100.00"))], currency="EUR")
    assert invoice_to_dict(inv) == {
        "number": "INV-9",
        "client_id": "c-000",
        "currency": "EUR",
        "lines": [
            {"description": "seats", "quantity": "2", "unit_price": "50.00", "amount": "100.00"},
            {"description": "support", "quantity": "1", "unit_price": "100.00", "amount": "100.00"},
        ],
        "subtotal": "200.00",
        "tax": "10.00",
        "total": "210.00",
    }


def test_empty_invoice():
    out = invoice_to_dict(Invoice("INV-0", "c-000"))
    assert out["lines"] == [] and out["total"] == "0.00"
