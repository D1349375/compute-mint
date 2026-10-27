"""Small text and sequence helpers (generic, no business logic)."""


def chunked(items, size: int) -> list[list]:
    """Split ``items`` into lists of ``size``; the last one may be shorter."""
    if size < 1:
        raise ValueError("size must be >= 1")
    return [list(items[i:i + size]) for i in range(0, len(items) - size + 1, size)]


def initials(name: str) -> str:
    """``"ada king lovelace"`` becomes ``"AKL"``."""
    return "".join(part[0].upper() for part in name.split())
