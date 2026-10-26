"""Upstreams the gateway forwards to.

`MockUpstream` stands in for the Meta Model API: a scripted solver produces the replies, tokens
are estimated from characters (bench/tokens.py) and prompt-cache hits come from a prefix-cache
simulation (bench/cachesim.py). `RecordingTransport` wraps any upstream and keeps a copy of every
request body that leaves the gateway; the canary check reads that copy, not the gateway's own
ledger, so it observes what really crossed the boundary.

`MetaUpstream` is the reserved interface for the real API. It is deliberately not implemented in
this round: the models have not been approved, so nothing in bench may make a network call.
"""
import json
from dataclasses import dataclass, field

import httpx

from .repos import solution_files
from .solver import ScriptedSolver
from .taskmodel import Task
from .tokens import MESSAGE_OVERHEAD, weight
from .cachesim import PrefixCache


@dataclass
class RecordedRequest:
    seq: int
    task_id: str
    model: str
    body: dict


@dataclass
class RecordingTransport(httpx.AsyncBaseTransport):
    inner: httpx.AsyncBaseTransport
    requests: list[RecordedRequest] = field(default_factory=list)
    current_task: str = ""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(RecordedRequest(len(self.requests), self.current_task, body.get("model", ""), body))
        return await self.inner.handle_async_request(request)


class MockUpstream:
    kind = "mock"

    def __init__(self, cache_block_tokens: int = 64) -> None:
        self.cache = PrefixCache(cache_block_tokens)
        self.solver: ScriptedSolver | None = None

    def begin_task(self, task: Task) -> None:
        self.solver = ScriptedSolver(task, solution_files(task.id))

    def transport(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.solver is None:
            raise RuntimeError("begin_task() was not called")
        body = json.loads(request.content)
        messages = body["messages"]
        message = self.solver.reply(messages)

        segments = [json.dumps(body.get("tools") or [], sort_keys=True, ensure_ascii=False)]
        segments += [json.dumps(m, sort_keys=True, ensure_ascii=False) for m in messages]
        prompt_tokens, cached = self.cache.lookup_and_insert(body["model"], segments)
        reply_text = (message.get("content") or "") + json.dumps(message.get("tool_calls") or [], ensure_ascii=False)
        completion = max(1, round(weight(reply_text) + MESSAGE_OVERHEAD))
        return httpx.Response(200, json={
            "id": "mock", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion,
                      "prompt_tokens_details": {"cached_tokens": cached}},
        })


class MetaUpstream:
    """Reserved interface for the real Meta Model API (usage and cache hits come from the response).

    Not implemented on purpose. A later round builds `transport()` from httpx.AsyncHTTPTransport()
    and the API key in META_API_KEY; everything else in bench (agent loop, arms, canary check,
    reports) is already upstream-agnostic. The `naive` arm never uses an upstream at all.
    """
    kind = "meta"

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "--upstream meta is reserved: no model has been approved yet, and bench makes no network calls in "
            "this round. Use --upstream mock.")


def make_upstream(kind: str, **options):
    if kind == "mock":
        return MockUpstream(**options)
    if kind == "meta":
        return MetaUpstream()
    raise ValueError(f"unknown upstream {kind!r}")
