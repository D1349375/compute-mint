"""Deterministic detectors for FLOOR content (credentials and personal information).

Regex detection under-reports sensitivity (it cannot see business confidentiality),
so it is only the first layer; the semantic judge sits on top of it.
"""
import re
from dataclasses import dataclass

# kind -> pattern. Order matters: earlier kinds win on overlapping spans.
PATTERNS: dict[str, re.Pattern] = {
    "PRIVATE_KEY": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    "API_KEY": re.compile(
        r"\b(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
        r"|xox[abpr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})"
    ),
    # Patterns with a named group "v" mask only that group (the value, not the key name).
    "BEARER": re.compile(r"Bearer (?P<v>[A-Za-z0-9._-]{24,})"),
    "SECRET_ASSIGN": re.compile(
        r"(?i)(?:api[_-]?key|secret|password|passwd|token)[\"']?\s*[:=]\s*[\"']?(?P<v>[A-Za-z0-9_\-./+]{12,})"
    ),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "TW_PHONE": re.compile(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)"),
    "TW_ID": re.compile(r"\b[A-Z][12]\d{8}\b"),
    "CARD": re.compile(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)"),
}

# Addresses that are not personal information (service and placeholder domains).
EMAIL_ALLOW = re.compile(r"@(?:example\.(?:com|org)|users\.noreply\.github\.com|anthropic\.com)$", re.I)


@dataclass(frozen=True)
class Span:
    kind: str
    start: int
    end: int
    text: str


def find_spans(text: str) -> list[Span]:
    """Non-overlapping FLOOR spans in `text`, left to right."""
    found: list[Span] = []
    for kind, pat in PATTERNS.items():
        for m in pat.finditer(text):
            if kind == "EMAIL" and EMAIL_ALLOW.search(m.group(0)):
                continue
            g = "v" if "v" in pat.groupindex else 0
            s = Span(kind, m.start(g), m.end(g), m.group(g))
            if not any(s.start < f.end and f.start < s.end for f in found):
                found.append(s)
    return sorted(found, key=lambda s: s.start)


def has_floor(text: str) -> bool:
    return bool(find_spans(text))
