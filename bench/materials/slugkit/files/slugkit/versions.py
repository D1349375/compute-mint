"""Dotted version strings."""


def parse_version(text: str) -> tuple:
    """``"v1.10.2"`` becomes ``(1, 10, 2)``."""
    return tuple(text.strip().lstrip("v").split("."))


def compare_versions(a: str, b: str) -> int:
    """Return -1, 0 or 1. Missing trailing parts count as zero (``"1.2" == "1.2.0"``)."""
    pa, pb = parse_version(a), parse_version(b)
    return (pa > pb) - (pa < pb)
