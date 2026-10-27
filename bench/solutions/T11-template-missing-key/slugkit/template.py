"""Tiny ``{{ name }}`` placeholder renderer."""
import re

_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render(template: str, **values) -> str:
    """Replace ``{{ name }}`` placeholders with ``values``.

    Raises ``KeyError`` naming the first placeholder that has no value.
    """
    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(name)
        return str(values[name])

    return _VAR.sub(substitute, template)
