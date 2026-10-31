"""Decide which lane a request goes to and assemble what is actually sent.

Contributor requests are always rebuilt from a masked copy of the context. The raw
history is never forwarded to Contributor (Meta Model API ToS §6.1: earlier content
included in a Contributor request becomes Contributor content).
"""
import copy
import json
from dataclasses import dataclass, field

from .context import Provenance, label_messages, message_text
from .detect import has_floor
from .labels import Label, contributable, join
from .origin import Origin, message_origins, origin_allows_contributor
from .vault import Vault

CONTRIBUTOR = "contributor"
STANDARD = "standard"
LOCAL = "local"    # a model on this machine; nothing leaves it
HELD = "held"      # not sent anywhere (see billing.py)


@dataclass
class Decision:
    lane: str
    messages: list[dict]          # exactly what goes upstream
    context_label: Label          # label of the context the model will see
    masked_spans: int = 0
    reason: str = ""
    blocked_by: list[int] = field(default_factory=list)  # indexes that kept it off Contributor


def _mask_message(msg: dict, vault: Vault) -> tuple[dict, int]:
    m = copy.deepcopy(msg)
    total = 0
    content = m.get("content")
    if isinstance(content, str):
        m["content"], n = vault.mask(content)
        total += n
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"], n = vault.mask(part["text"])
                total += n
    for call in m.get("tool_calls") or []:
        fn = call.get("function") or {}
        if isinstance(fn.get("arguments"), str):
            fn["arguments"], n = vault.mask(fn["arguments"])
            total += n
    return m, total


def mask_fields(value, vault: Vault) -> tuple[object, int]:
    """Mask the strings of a JSON value (tool definitions and other request fields next to the messages)."""
    if isinstance(value, str):
        return vault.mask(value)
    if isinstance(value, list):
        pairs = [mask_fields(v, vault) for v in value]
        return [v for v, _ in pairs], sum(n for _, n in pairs)
    if isinstance(value, dict):
        pairs = {k: mask_fields(v, vault) for k, v in value.items()}
        return {k: v for k, (v, _) in pairs.items()}, sum(n for _, n in pairs.values())
    return value, 0


def route(messages: list[dict], *, baseline: Label, dial: Label, vault: Vault, provenance: Provenance,
          baseline_for=None, origins: list[Origin] | None = None, unlabeled: str | None = None) -> Decision:
    # Contributor needs the label to fit the dial AND every message to come from an allowed origin.
    # `unlabeled` says the request holds content that cannot be judged (see responses.py): it stays off Contributor.
    if origins is None:
        origins = message_origins(messages, provenance)
    labeled = label_messages(messages, baseline, provenance, baseline_for)
    raw_label = join(*(lm.effective for lm in labeled))

    masked, residuals, spans = [], [], 0
    running_raw = Label.PUBLIC
    for i, lm in enumerate(labeled):
        m, n = _mask_message(lm.msg, vault)
        spans += n
        base = baseline_for(i, lm.msg) if baseline_for else baseline
        residual_own = Label.FLOOR if has_floor(message_text(m)) else base
        if lm.msg.get("role") == "assistant":
            known = provenance.lookup(lm.msg)
            # An assistant message we did not generate may paraphrase anything it saw,
            # so masking its text does not lower what it was derived from.
            residual = join(residual_own, known if known is not None else running_raw)
        else:
            residual = residual_own
        masked.append(m)
        residuals.append(residual)
        running_raw = join(running_raw, lm.effective)

    by_origin = [i for i, o in enumerate(origins) if not origin_allows_contributor(o)]
    blocked = sorted({i for i, r in enumerate(residuals) if not contributable(r, dial)} | set(by_origin))
    if not blocked and not unlabeled:
        return Decision(CONTRIBUTOR, masked, join(*residuals), spans,
                        reason="all context contributable after masking")
    why = getattr(baseline_for, "why", None)
    causes = sorted({c for i in blocked for c in (why(i) if why else ())})
    if unlabeled and not blocked:
        return Decision(STANDARD, [copy.deepcopy(m) for m in messages], join(raw_label, Label.CONFIDENTIAL), 0,
                        reason=unlabeled)
    return Decision(STANDARD, [copy.deepcopy(m) for m in messages],
                    join(raw_label, Label.CONFIDENTIAL) if unlabeled else raw_label, 0,
                    reason=f"{len(blocked)} message(s) not contributable"
                           + (f" ({len(by_origin)} by origin)" if by_origin else "")
                           + (f" [{', '.join(causes)}]" if causes else "")
                           + (f"; {unlabeled}" if unlabeled else ""), blocked_by=blocked)


def rehydrate_response(body: dict, vault: Vault) -> dict:
    out = copy.deepcopy(body)
    for choice in out.get("choices", []):
        msg = choice.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = vault.rehydrate(msg["content"])
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            if isinstance(fn.get("arguments"), str):
                fn["arguments"] = vault.rehydrate_json(fn["arguments"])
    return out


def payload_digest(payload: list[dict] | dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
