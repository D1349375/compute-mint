"""Parse short duration strings such as ``"1h30m"``."""
import re

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PART = re.compile(r"(\d+)([smhd])")


def parse_duration(text: str) -> int:
    """Return the number of seconds in ``text`` (``"1h30m"`` is 5400).

    Parts are whole numbers followed by one of ``s``, ``m``, ``h`` or ``d``. Anything else
    raises ``ValueError``.
    """
    text = text.strip().lower()
    if not text or "".join(m.group(0) for m in _PART.finditer(text)) != text:
        raise ValueError(f"invalid duration: {text!r}")
    return sum(int(n) * UNITS[u] for n, u in _PART.findall(text))
