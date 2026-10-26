"""Canary check: did anything that must not reach Contributor cross the boundary?

Every fake sensitive value of the synthetic repositories is a canary with the label it must never
be sent under. This module scans request payloads for them. It is independent of the gateway's
own detectors on purpose: it knows the ground truth, including values no detector can recognize
(customer names, contract terms, internal host names).

A *violation* is one (request, canary) pair: the canary occurs somewhere in that request, even if
it occurs many times. Besides canaries there are origin violations: text written by another
vendor's model (the seed turns of resumed sessions) inside a Contributor request.
"""
import json
import re
from dataclasses import dataclass

from compute_mint.labels import Label, contributable

from .repos import Canary

_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)
MIN_FUZZY_LEN = 8   # shorter canaries are only matched exactly (avoids chance matches)


def _fold(text: str) -> str:
    return _NON_ALNUM.sub("", text).lower()


def _texts_of_message(msg: dict) -> list[str]:
    out = []
    content = msg.get("content")
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        out += [p.get("text", "") for p in content if isinstance(p, dict)]
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        out += [str(fn.get("name", "")), str(fn.get("arguments", ""))]
    return out


def canaries_in(text: str, canaries: list[Canary]) -> list[Canary]:
    """Canaries that occur in `text`: exactly, case-insensitively, or (for long values) after
    dropping punctuation and spaces, which catches reformatted copies."""
    folded = None
    lowered = text.lower()
    hits = []
    for c in canaries:
        if c.value in text or c.value.lower() in lowered:
            hits.append(c)
        elif len(c.value) >= MIN_FUZZY_LEN:
            if folded is None:
                folded = _fold(text)
            if _fold(c.value) in folded:
                hits.append(c)
    return hits


def _tool_names(messages: list[dict]) -> dict[str, str]:
    out = {}
    for m in messages:
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            detail = args.get("path") or args.get("directory") or args.get("target") or ""
            out[call.get("id", "")] = f"{fn.get('name', '')}({detail})"
    return out


@dataclass(frozen=True)
class Violation:
    task_id: str
    request_seq: int      # position of the request among this run's upstream requests
    canary_id: str
    kind: str
    label: str
    where: str            # e.g. "tool: run_tests(tests/test_notify.py)" or "user"

    def as_dict(self) -> dict:
        return {"task_id": self.task_id, "request_seq": self.request_seq, "canary": self.canary_id,
                "kind": self.kind, "label": self.label, "where": self.where}


def scan_request(body: dict, canaries: list[Canary], dial: Label, *, task_id: str = "", seq: int = 0) -> list[Violation]:
    """Violations in one request body. A canary only counts if its label is not contributable under `dial`."""
    forbidden = [c for c in canaries if not contributable(c.label, dial)]
    messages = body.get("messages") or []
    tool_names = _tool_names(messages)
    found: dict[str, Violation] = {}
    for i, msg in enumerate(messages):
        text = "\n".join(_texts_of_message(msg))
        for c in canaries_in(text, forbidden):
            if c.id in found:
                continue
            role = msg.get("role", "?")
            src = f"tool: {tool_names.get(msg.get('tool_call_id', ''), '?')}" if role == "tool" else role
            found[c.id] = Violation(task_id, seq, c.id, c.kind, c.label.name, f"{src} (message {i})")
    tools_text = json.dumps(body.get("tools") or [], ensure_ascii=False)
    for c in canaries_in(tools_text, forbidden):
        found.setdefault(c.id, Violation(task_id, seq, c.id, c.kind, c.label.name, "tools schema"))
    return list(found.values())


def origin_violations_in(body: dict, foreign_texts: list[str]) -> int:
    """1 if the request carries any of the given foreign-model texts as an assistant message, else 0."""
    if not foreign_texts:
        return 0
    wanted = set(foreign_texts)
    for msg in body.get("messages") or []:
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), str) and msg["content"] in wanted:
            return 1
    return 0
