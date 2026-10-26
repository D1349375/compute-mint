"""Session-consistent pseudonymization: mask FLOOR values with placeholders and restore them.

The same value always maps to the same placeholder within a session, so the model can
still reason about "the same key" or "the same customer" across turns. Originals never
leave the gateway.
"""
import re

from .detect import find_spans

PLACEHOLDER = re.compile(r"⟨([A-Z_]+)_(\d+)⟩")


class Vault:
    def __init__(self) -> None:
        self._by_value: dict[str, str] = {}
        self._by_placeholder: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def _placeholder_for(self, kind: str, value: str) -> str:
        if value not in self._by_value:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            ph = f"⟨{kind}_{self._counts[kind]}⟩"
            self._by_value[value] = ph
            self._by_placeholder[ph] = value
        return self._by_value[value]

    def mask(self, text: str) -> tuple[str, int]:
        """Return (masked_text, number_of_spans_masked)."""
        spans = find_spans(text)
        if not spans:
            return text, 0
        out, pos = [], 0
        for s in spans:
            out.append(text[pos:s.start])
            out.append(self._placeholder_for(s.kind, s.text))
            pos = s.end
        out.append(text[pos:])
        return "".join(out), len(spans)

    def rehydrate(self, text: str) -> str:
        return PLACEHOLDER.sub(lambda m: self._by_placeholder.get(m.group(0), m.group(0)), text)

    def originals(self) -> list[str]:
        return list(self._by_value)
