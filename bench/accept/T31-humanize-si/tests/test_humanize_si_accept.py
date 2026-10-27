from slugkit.humanize import human_size


def test_si_units():
    assert human_size(1500, si=True) == "1.5 kB"
    assert human_size(999, si=True) == "999 B"
    assert human_size(2_000_000, si=True) == "2.0 MB"


def test_binary_is_still_the_default():
    assert human_size(1536) == "1.5 KiB"
    assert human_size(1024) == "1.0 KiB"
    assert human_size(1000) == "1000 B"
