from datetime import date

from legacy.legacy_import import parse_legacy_date, parse_legacy_row


def test_two_digit_years_after_2000():
    assert parse_legacy_date("07/03/26") == date(2026, 3, 7)


def test_two_digit_years_in_the_nineties():
    assert parse_legacy_date("31/12/98") == date(1998, 12, 31)


def test_row_parsing():
    row = parse_legacy_row("A0007|07/03/26|1250.50|TWD")
    assert row["account"] == "A0007" and row["issued"] == date(2026, 3, 7) and str(row["amount"]) == "1250.50"
