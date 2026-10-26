from slugkit.ranges import merge_ranges


def test_overlapping_ranges_merge():
    assert merge_ranges([(1, 3), (2, 5), (7, 8)]) == [(1, 5), (7, 8)]


def test_touching_ranges_merge():
    assert merge_ranges([(1, 2), (2, 3)]) == [(1, 3)]


def test_unsorted_input_is_accepted():
    assert merge_ranges([(7, 8), (1, 3), (2, 5)]) == [(1, 5), (7, 8)]
