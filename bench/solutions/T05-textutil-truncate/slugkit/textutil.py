"""Text helpers."""


def truncate(text: str, width: int, suffix: str = "...") -> str:
    """Shorten ``text`` to at most ``width`` characters, ending in ``suffix`` when it was cut.

    Text that already fits is returned unchanged. ``width`` must be able to hold the suffix.
    """
    if width < len(suffix):
        raise ValueError("width must be at least the length of the suffix")
    if len(text) <= width:
        return text
    return text[:width - len(suffix)] + suffix
