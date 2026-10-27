"""Payment terms to due dates."""
import calendar
from datetime import date, timedelta


def end_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def due_date(issued: date, terms: str) -> date:
    """``net30``: 30 days after ``issued``; ``eom``: end of the issue month;
    ``net30eom``: the end of the month in which day 30 falls."""
    if terms == "eom":
        return end_of_month(issued)
    if terms.startswith("net"):
        days = int(terms[3:].removesuffix("eom"))
        due = issued + timedelta(days=days)
        return end_of_month(due) if terms.endswith("eom") else due
    raise ValueError(f"unknown payment terms: {terms!r}")
