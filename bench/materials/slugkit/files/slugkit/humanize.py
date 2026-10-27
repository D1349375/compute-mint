"""Human-readable numbers."""

_UNITS = ["B", "KiB", "MiB", "GiB", "TiB"]


def human_size(n: int) -> str:
    """Format a byte count with binary units: ``1536`` becomes ``"1.5 KiB"``."""
    size = float(n)
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")
