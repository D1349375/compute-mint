"""Customer-facing reminder texts."""
from decimal import Decimal


def reminder_text(client: dict, invoice_number: str, days_overdue: int, amount: Decimal) -> str:
    unit = "days"
    return (
        f"Dear {client['contact']},\n\n"
        f"Invoice {invoice_number} for {client['name']} ({amount} {client.get('currency', 'TWD')}) "
        f"is {days_overdue} {unit} overdue.\n"
        "Please arrange payment or contact accounts receivable.\n\n"
        "Kestrel Works Ltd. Accounts Receivable"
    )
