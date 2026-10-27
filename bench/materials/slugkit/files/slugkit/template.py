"""Tiny ``{{ name }}`` placeholder renderer."""
import re

_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render(template: str, **values) -> str:
    """Replace ``{{ name }}`` placeholders with ``values``.

    Raises ``KeyError`` naming the first placeholder that has no value.
    """
    return _VAR.sub(lambda m: str(values.get(m.group(1))), template)
