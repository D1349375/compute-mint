"""Deterministic detectors for FLOOR content (credentials and personal information).

Regex detection under-reports sensitivity (it cannot see business confidentiality),
so it is only the first layer; the semantic judge sits on top of it.
"""
import re
from dataclasses import dataclass

# All boundaries are ASCII (re.ASCII): to Unicode, a Chinese character is a word character, so a key glued to
# Chinese text would have no `\b` at all. A word start also counts right after a JSON escape: tool-call arguments
# are JSON text, where the two characters of an escaped line break put a letter directly in front of what follows.
WORD_START = r"(?:\b|(?<=\\[nrtfb])|(?<=\\u[0-9a-fA-F]{4}))"

def _ascii(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.ASCII)


# kind -> pattern. Order matters: earlier kinds win on overlapping spans.
PATTERNS: dict[str, re.Pattern] = {
    "PRIVATE_KEY": _ascii(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    "API_KEY": _ascii(
        WORD_START + r"(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
        r"|xox[abpr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})"
    ),
    # Patterns with a named group "v" mask only that group (the value, not the key name).
    "BEARER": _ascii(r"Bearer (?P<v>[A-Za-z0-9._-]{24,})"),
    "SECRET_ASSIGN": _ascii(
        r"(?i)(?:api[_-]?key|secret|password|passwd|token|密碼|密码|金鑰|密鑰|密钥|權杖|令牌|口令)[\"']?\s*[:=]\s*[\"']?(?P<v>[A-Za-z0-9_\-./+]{12,})"
    ),
    "EMAIL": _ascii(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "TW_PHONE": _ascii(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)"),
    "TW_ID": _ascii(WORD_START + r"[A-Z][12]\d{8}\b"),
    "CARD": _ascii(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)"),
}

# Addresses that are not personal information (service and placeholder domains).
EMAIL_ALLOW = re.compile(r"@(?:example\.(?:com|org)|users\.noreply\.github\.com|anthropic\.com)$", re.I)


_HALF_WIDTH = {**{c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}, 0x3000: 0x20}


@dataclass(frozen=True)
class Span:
    kind: str
    start: int
    end: int
    text: str


def half_width(text: str) -> str:
    """Full-width forms (`＠`, `：`, `０`) as ASCII, one character for one, so offsets stay valid."""
    return text if text.isascii() else text.translate(_HALF_WIDTH)


def find_spans(text: str) -> list[Span]:
    """Non-overlapping FLOOR spans in `text`, left to right."""
    found: list[Span] = []
    probe = half_width(text)
    for kind, pat in PATTERNS.items():
        for m in pat.finditer(probe):
            if kind == "EMAIL" and EMAIL_ALLOW.search(m.group(0)):
                continue
            g = "v" if "v" in pat.groupindex else 0
            s = Span(kind, m.start(g), m.end(g), text[m.start(g):m.end(g)])
            if not any(s.start < f.end and f.start < s.end for f in found):
                found.append(s)
    return sorted(found, key=lambda s: s.start)


def has_floor(text: str) -> bool:
    return bool(find_spans(text))
