from slugkit.csvlite import parse_line


def test_semicolon_delimiter():
    assert parse_line("a;b;c", delimiter=";") == ["a", "b", "c"]


def test_quotes_still_protect_the_delimiter():
    assert parse_line('a;"b;c";d', delimiter=";") == ["a", "b;c", "d"]


def test_comma_is_just_text_with_another_delimiter():
    assert parse_line("a,b;c", delimiter=";") == ["a,b", "c"]


def test_default_is_unchanged():
    assert parse_line('x,"y,z"') == ["x", "y,z"]
