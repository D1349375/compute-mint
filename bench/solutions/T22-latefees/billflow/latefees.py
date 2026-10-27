"""Late fees on overdue invoices."""
from decimal import Decimal

from .money import to_money


def late_fee(amount: Decimal, days_overdue: int, daily_rate: Decimal = Decimal("0.0005"),
             cap: Decimal = Decimal("0.15")) -> Decimal:
    """Fee for ``days_overdue`` days: ``amount * daily_rate * days``, rounded to cents and never
    more than ``amount * cap``. Nothing is due for zero or negative days."""
    if days_overdue <= 0:
        return to_money(0)
    return min(to_money(amount * daily_rate * days_overdue), to_money(amount * cap))
