"""Money arithmetic. All amounts are Decimals with two places; rounding is half-even."""
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")


def to_money(value) -> Decimal:
    """Round any number-like value to whole cents."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def split_amount(total: Decimal, parts: int) -> list[Decimal]:
    """Split ``total`` into ``parts`` shares that add up exactly to ``total``.

    Shares differ by at most one cent; the extra cents go to the first shares.
    """
    if parts < 1:
        raise ValueError("parts must be >= 1")
    share = (total / parts).quantize(CENT, rounding=ROUND_DOWN)
    return [share] * parts
