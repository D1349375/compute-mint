"""Interval helpers."""


def merge_ranges(ranges):
    """Merge overlapping or touching ``(start, end)`` pairs.

    The result is sorted by start. The input does not have to be sorted.
    """
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
