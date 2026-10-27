"""Word wrapping."""


def wrap_words(text: str, width: int) -> list[str]:
    """Greedy word wrap: pack as many words as fit into each line of at most ``width``
    characters. A word longer than ``width`` stays on a line of its own."""
    if width < 1:
        raise ValueError("width must be >= 1")
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
