import pytest

from slugkit.durations import parse_duration


def test_seconds_and_minutes():
    assert parse_duration("90s") == 90
    assert parse_duration("5m") == 300


def test_hours():
    assert parse_duration("2h") == 7200


def test_combined():
    assert parse_duration("1h30m") == 5400


def test_invalid_raises():
    with pytest.raises(ValueError):
        parse_duration("soon")
