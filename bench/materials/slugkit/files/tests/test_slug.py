from slugkit.slug import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_accents_are_folded():
    assert slugify("Crème Brûlée") == "creme-brulee"


def test_custom_separator():
    assert slugify("a b c", sep="_") == "a_b_c"


def test_max_length_never_ends_with_separator():
    assert slugify("Hello, World! Again", max_length=12) == "hello-world"
