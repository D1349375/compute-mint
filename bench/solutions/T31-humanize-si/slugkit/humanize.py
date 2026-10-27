"""Human-readable numbers."""

_BINARY_UNITS = ["B", "KiB", "MiB", "GiB", "TiB"]
_SI_UNITS = ["B", "kB", "MB", "GB", "TB"]


def human_size(n: int, si: bool = False) -> str:
    """Format a byte count: binary units by default (``1536`` is ``"1.5 KiB"``), powers of 1000
    with ``si=True`` (``1500`` is ``"1.5 kB"``)."""
    base, units = (1000, _SI_UNITS) if si else (1024, _BINARY_UNITS)
    size = float(n)
    for unit in units:
        if size < base or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= base
    raise AssertionError("unreachable")
