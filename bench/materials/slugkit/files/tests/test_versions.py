from slugkit.versions import compare_versions, parse_version


def test_parse_returns_integers():
    assert parse_version("v1.10.2") == (1, 10, 2)


def test_compare_is_numeric_not_lexicographic():
    assert compare_versions("1.10.0", "1.9.2") == 1


def test_missing_parts_count_as_zero():
    assert compare_versions("1.2", "1.2.0") == 0


def test_older_is_negative():
    assert compare_versions("0.9", "1.0") == -1
