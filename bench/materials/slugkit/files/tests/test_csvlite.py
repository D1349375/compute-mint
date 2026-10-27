from slugkit.csvlite import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_quoted_field_with_comma():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_doubled_quote_is_a_literal_quote_and_empty_trailing_field_is_kept():
    assert parse_line('"say ""hi""",') == ['say "hi"', ""]
