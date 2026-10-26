"""Invoices and their totals."""
from dataclasses import dataclass, field
from decimal import Decimal

from .money import to_money

ZERO = Decimal("0.00")


@dataclass
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal

    def amount(self) -> Decimal:
        return to_money(self.quantity * self.unit_price)


@dataclass
class Invoice:
    number: str
    client_id: str
    lines: list[Line] = field(default_factory=list)
    tax_rate: Decimal = Decimal("0.05")
    currency: str = "TWD"

    def subtotal(self) -> Decimal:
        return sum((line.amount() for line in self.lines), ZERO)

    def tax(self) -> Decimal:
        """Tax on the whole invoice, rounded once."""
        return sum((to_money(line.amount() * self.tax_rate) for line in self.lines), ZERO)

    def total(self) -> Decimal:
        return self.subtotal() + self.tax()
