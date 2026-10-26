"""Remove personal data from text before it is logged or shared."""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\b09\d{2}-?\d{3}-?\d{3}\b")


def redact_pii(text: str) -> str:
    """Replace e-mail addresses with ``[email]`` and Taiwanese mobile numbers (dashed or
    plain digits) with ``[phone]``."""
    text = EMAIL.sub("[email]", text)
    return PHONE.sub("[phone]", text)
