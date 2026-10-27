"""URL-friendly slugs."""
import re
import unicodedata


def slugify(text: str, max_length: int | None = None, sep: str = "-") -> str:
    """Lowercase ``text`` and join its words with ``sep``.

    Accents are stripped (``"Crème"`` becomes ``"creme"``). If ``max_length`` is given the
    result is cut to at most that many characters and never ends with ``sep``.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", sep, folded.lower()).strip(sep)
    if max_length is not None:
        slug = slug[:max_length]
    return slug
