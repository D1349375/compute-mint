from datetime import date

import pytest

from billflow.duedates import due_date


def test_net_terms():
    assert due_date(date(2026, 1, 15), "net30") == date(2026, 2, 14)


def test_end_of_month():
    assert due_date(date(2026, 2, 10), "eom") == date(2026, 2, 28)


def test_net_days_then_end_of_month():
    assert due_date(date(2026, 1, 20), "net30eom") == date(2026, 2, 28)


def test_unknown_terms():
    with pytest.raises(ValueError):
        due_date(date(2026, 1, 1), "whenever")
