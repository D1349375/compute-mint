"""Invoice serialization for the accounting API."""
from .invoice import Invoice


def invoice_to_dict(invoice: Invoice) -> dict:
    """Plain-dict form of an invoice. Decimal values are converted with ``str()``."""
    return {
        "number": invoice.number,
        "client_id": invoice.client_id,
        "currency": invoice.currency,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "amount": str(line.amount()),
            }
            for line in invoice.lines
        ],
        "subtotal": str(invoice.subtotal()),
        "tax": str(invoice.tax()),
        "total": str(invoice.total()),
    }
