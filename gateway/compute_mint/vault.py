"""Session-consistent pseudonymization: mask FLOOR values with placeholders and restore them.

The same value always maps to the same placeholder within a session, so the model can
still reason about "the same key" or "the same customer" across turns. Originals never
leave the gateway.
"""
import json
import re

from .detect import find_spans

PLACEHOLDER = re.compile(r"⟨([A-Z_]+)_(\d+)⟩")
# A placeholder's brackets written as JSON escapes (backslash-u-2-7-e-8 and ...e-9), unless the backslash is itself escaped.
ESCAPED_BRACKET = re.compile(r"(?<!\\)((?:\\\\)*)\\u27[eE]([89])")
# The end of a chunk that may be the start of such an escape: the whole run of backslashes, since only the
# run's length tells whether the last one starts an escape.
PARTIAL_ESCAPE = re.compile(r"\\+(?:u(?:2(?:7[eE]?)?)?)?$")


def unescape_brackets(text: str) -> str:
    """Write the placeholder brackets that JSON text spells as escapes as the characters; the JSON stays the same."""
    return ESCAPED_BRACKET.sub(lambda m: m.group(1) + ("⟨" if m.group(2) == "8" else "⟩"), text)


def _json_safe(value: str) -> str:
    """`value` as the inside of a JSON string. A value masked out of JSON text is already in that form: leave it."""
    try:
        json.loads(f'"{value}"')
        return value
    except ValueError:
        return json.dumps(value, ensure_ascii=False)[1:-1]


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

    def rehydrate_json(self, text: str) -> str:
        """Rehydrate text that is JSON (tool-call arguments), so that it stays JSON."""
        def restore(m: re.Match) -> str:
            value = self._by_placeholder.get(m.group(0))
            return m.group(0) if value is None else _json_safe(value)
        return PLACEHOLDER.sub(restore, unescape_brackets(text))

    def may_become_placeholder(self, tail: str) -> bool:
        """Whether `tail` is the start of a placeholder this vault can restore."""
        return any(ph.startswith(tail) and ph != tail for ph in self._by_placeholder)

    def originals(self) -> list[str]:
        return list(self._by_value)


class StreamRestorer:
    """Rehydrates text that arrives in pieces: a tail that may still become a placeholder is held back."""

    def __init__(self, vault: Vault | None, json_text: bool = False) -> None:
        self.vault, self.held, self.json_text = vault, "", json_text
        self.restore = None if vault is None else vault.rehydrate_json if json_text else vault.rehydrate

    def feed(self, text: str) -> str:
        if self.vault is None:
            return text
        text, partial = self.held + text, ""
        if self.json_text:
            text = unescape_brackets(text)
            cut = PARTIAL_ESCAPE.search(text)
            if cut:
                text, partial = text[:cut.start()], cut.group(0)
        start = text.rfind("⟨")
        tail = text[start:] if start >= 0 else ""
        if tail and self.vault.may_become_placeholder(tail):
            self.held, text = tail + partial, text[:start]
        else:
            self.held = partial
        return self.restore(text)

    def flush(self) -> str:
        held, self.held = self.held, ""
        return self.restore(held) if self.vault else held
