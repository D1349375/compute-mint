"""Prefix-cache simulation.

Provider prompt caches match on the longest common prefix of the serialized prompt. This
module models that for the mock upstream:

- a prompt is a list of segments (the tool schema, then one JSON string per message);
- a trie of every prompt seen so far is kept per model, shared across sessions (a real cache is
  keyed on the prefix, not on a conversation);
- for a new prompt the cached length is the longest prefix that equals the prefix of any earlier
  prompt of the same model: whole segments first, then the common characters of the first
  segment that differs;
- the cached token count is rounded down to a multiple of `block_tokens`, and at least one
  token is always uncached.

Not modelled: cache expiry (TTL), a minimum cacheable length, and per-organization isolation.
Contributor and Standard are different models, so they never share entries.
"""
import hashlib
from dataclasses import dataclass, field

from .tokens import MESSAGE_OVERHEAD, weight


@dataclass
class _Node:
    children: dict[str, "_Node"] = field(default_factory=dict)
    text: dict[str, str] = field(default_factory=dict)  # child key -> the segment text, for partial matches


def _key(segment: str) -> str:
    return hashlib.sha1(segment.encode("utf-8")).hexdigest()


class PrefixCache:
    def __init__(self, block_tokens: int = 64) -> None:
        self.block_tokens = block_tokens
        self._roots: dict[str, _Node] = {}

    def lookup_and_insert(self, model: str, segments: list[str]) -> tuple[float, int]:
        """Return (prompt_tokens, cached_tokens) for a prompt and remember it for later prompts."""
        root = self._roots.setdefault(model, _Node())
        total = sum(weight(s) + MESSAGE_OVERHEAD for s in segments)

        matched = 0.0
        node = root
        diverged = False
        for seg in segments:
            key = _key(seg)
            if not diverged:
                if key in node.children:
                    matched += weight(seg) + MESSAGE_OVERHEAD
                else:
                    diverged = True
                    best = 0
                    for other in node.text.values():
                        n = 0
                        limit = min(len(other), len(seg))
                        while n < limit and other[n] == seg[n]:
                            n += 1
                        best = max(best, n)
                    matched += weight(seg[:best])
            child = node.children.get(key)
            if child is None:
                child = node.children[key] = _Node()
                node.text[key] = seg
            node = child

        prompt_tokens = max(1, round(total))
        cached = int(matched // self.block_tokens) * self.block_tokens
        return prompt_tokens, max(0, min(cached, prompt_tokens - 1))
