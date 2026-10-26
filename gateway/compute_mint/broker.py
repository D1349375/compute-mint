"""Context Broker: shrink what the model re-reads every turn without breaking the prompt cache.

Provider prompt caching is prefix-based. Cached reads cost about 1/8 of uncached input, so a
compressor that rewrites the history every turn usually costs more than it saves. The broker
therefore changes each message's representation at most once, and only at the moment that
message stops being the newest part of the prompt (where it was uncached anyway):

- tool outputs in the current turn (after the last assistant message) are sent in full;
- from the next turn on, long tool outputs are replaced by a compact version;
- the compact version is memoized per session, so every later prompt carries the identical
  text and the cached prefix keeps matching.

An optional project card is placed as the first system message. It only changes between
sessions, so it sits in the cached prefix.
"""
import copy
import re
from dataclasses import dataclass, field

from .context import fingerprint

SALIENT = re.compile(r"(?i)\b(error|exception|traceback|failed|failure|fatal|warning|assert|panic|denied|not found)\b")


@dataclass
class BrokerConfig:
    compact_over_chars: int = 4000   # tool outputs longer than this get compacted once they age
    head_chars: int = 1200
    tail_chars: int = 1200
    max_salient_lines: int = 40


@dataclass
class BrokerStats:
    chars_in: int = 0
    chars_out: int = 0
    compacted: int = 0


def compact_text(text: str, cfg: BrokerConfig) -> str:
    """Deterministic compaction: head, tail, and the salient lines from the middle."""
    head, tail = text[:cfg.head_chars], text[-cfg.tail_chars:]
    middle = text[cfg.head_chars:len(text) - cfg.tail_chars]
    seen, salient = set(), []
    for line in middle.splitlines():
        key = line.strip()
        if key and key not in seen and SALIENT.search(key):
            seen.add(key)
            salient.append(line)
            if len(salient) >= cfg.max_salient_lines:
                break
    omitted = len(middle) - sum(len(s) + 1 for s in salient)
    parts = [head, f"\n[compute-mint: {omitted} chars omitted from an earlier tool output"]
    if salient:
        parts.append("; salient lines kept]\n" + "\n".join(salient) + "\n[...]\n")
    else:
        parts.append("]\n")
    parts.append(tail)
    return "".join(parts)


@dataclass
class Broker:
    cfg: BrokerConfig = field(default_factory=BrokerConfig)
    _memo: dict[str, str] = field(default_factory=dict)

    def _compact_once(self, msg: dict) -> str:
        key = fingerprint(msg)
        if key not in self._memo:
            self._memo[key] = compact_text(msg["content"], self.cfg)
        return self._memo[key]

    def apply(self, messages: list[dict], card: str | None = None) -> tuple[list[dict], BrokerStats]:
        stats = BrokerStats()
        last_assistant = max((i for i, m in enumerate(messages) if m.get("role") == "assistant"), default=-1)
        out = []
        if card:
            out.append({"role": "system", "content": card})
        for i, msg in enumerate(messages):
            m = copy.deepcopy(msg)
            content = m.get("content")
            if isinstance(content, str):
                stats.chars_in += len(content)
                aged = i < last_assistant
                if m.get("role") == "tool" and aged and len(content) > self.cfg.compact_over_chars:
                    m["content"] = self._compact_once(msg)
                    stats.compacted += 1
                stats.chars_out += len(m["content"])
            out.append(m)
        return out, stats
