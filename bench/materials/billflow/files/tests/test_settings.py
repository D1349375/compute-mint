from billflow.settings import parse_env


def test_plain_pairs_and_comments():
    assert parse_env("# comment\n\nA=1\nB = two\n") == {"A": "1", "B": "two"}


def test_quotes_are_removed():
    assert parse_env("A=\"x y\"\nB='z'\n") == {"A": "x y", "B": "z"}


def test_equals_sign_inside_the_value_is_kept():
    assert parse_env("URL=http://h/?a=b") == {"URL": "http://h/?a=b"}
