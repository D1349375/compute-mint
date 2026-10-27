from slugkit.humanize import human_size


def test_bytes():
    assert human_size(512) == "512 B"


def test_kibibytes():
    assert human_size(1536) == "1.5 KiB"


def test_exact_unit_boundary():
    assert human_size(1024) == "1.0 KiB"
