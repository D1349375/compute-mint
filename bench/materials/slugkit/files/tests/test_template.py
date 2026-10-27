import pytest

from slugkit.template import render


def test_replaces_placeholders():
    assert render("Hello {{ name }}!", name="Ada") == "Hello Ada!"


def test_whitespace_inside_braces_is_optional():
    assert render("{{a}}-{{ b }}", a=1, b=2) == "1-2"


def test_extra_values_are_ignored():
    assert render("x", unused=1) == "x"


def test_missing_value_raises_keyerror_with_the_name():
    with pytest.raises(KeyError, match="name"):
        render("Hello {{ name }}!")
