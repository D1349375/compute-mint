"""Upstreams the gateway forwards to.

`MockUpstream` stands in for the Meta Model API: a scripted solver produces the replies, tokens
are estimated from characters (bench/tokens.py) and prompt-cache hits come from a prefix-cache
simulation (bench/cachesim.py). `RecordingTransport` wraps any upstream and keeps a copy of every
request body that leaves the gateway; the canary check reads that copy, not the gateway's own
ledger, so it observes what really crossed the boundary.

`MetaUpstream` is the real Meta Model API (`--upstream meta`, key in META_API_KEY), with a spending cap.
Only `--upstream meta` makes a network call; the bench data is invented, so it may be sent.
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


class BudgetExceeded(RuntimeError):
    pass


class BudgetTransport(httpx.AsyncBaseTransport):
    """Real network with a spending cap and a few retries.

    The cost of every answer is computed from the `usage` the API returns and the Meta price table, the
    same way the gateway's ledger does, and added to `MetaUpstream.spent_usd`, which all arms share. Once
    the cap is reached no further request leaves the machine. Rate limits and server errors are retried
    (they are not billed), nothing else is."""

    def __init__(self, inner: httpx.AsyncBaseTransport, owner: type, retries: int = 3) -> None:
        self.inner, self.owner, self.retries = inner, owner, retries

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import asyncio
        from compute_mint.pricing import PRICES, Usage, cost

        for attempt in range(self.retries + 1):
            if self.owner.budget_usd and self.owner.spent_usd >= self.owner.budget_usd:
                self.owner.over_budget = True
                raise BudgetExceeded(f"spending cap of ${self.owner.budget_usd:.2f} reached "
                                     f"(${self.owner.spent_usd:.4f} spent); no request was sent")
            try:
                resp = await self.inner.handle_async_request(request)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                await resp.aread()
                await resp.aclose()
                await asyncio.sleep(2 ** attempt * 2)
                continue
            await resp.aread()
            if resp.status_code == 200:
                try:
                    data = json.loads(resp.content)
                    model = data.get("model", "")
                    if model in PRICES:
                        self.owner.spent_usd += cost(model, Usage.from_openai(data.get("usage")))
                        self.owner.requests += 1
                except ValueError:
                    pass
            return resp
        raise AssertionError("unreachable")


class MetaUpstream:
    """The real Meta Model API (usage and cache hits come from the response).

    The key is read from META_API_KEY and never printed or stored; the base URL from META_API_BASE.
    `budget_usd` (class level, shared by all arms of a process) stops the run when the computed spend
    reaches it. The `naive` arm never uses an upstream at all. Bench makes network calls only with
    `--upstream meta`; the default stays `mock`.
    """
    kind = "meta"
    spent_usd = 0.0
    requests = 0
    budget_usd = 0.0
    over_budget = False

    def __init__(self, *, budget_usd: float = 0.0, inner: httpx.AsyncBaseTransport | None = None, **_options) -> None:
        import os
        self.api_base = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
        self.api_key = os.environ.get("META_API_KEY", "")
        if not self.api_key and inner is None:
            raise RuntimeError("--upstream meta needs META_API_KEY (put it in .env at the repository root)")
        MetaUpstream.budget_usd = budget_usd or MetaUpstream.budget_usd
        self._inner = inner

    def begin_task(self, task: Task) -> None:
        pass

    def transport(self) -> httpx.AsyncBaseTransport:
        return BudgetTransport(self._inner or httpx.AsyncHTTPTransport(), MetaUpstream)


def make_upstream(kind: str, **options):
    if kind == "mock":
        return MockUpstream(cache_block_tokens=options.get("cache_block_tokens", 64))
    if kind == "meta":
        return MetaUpstream(**options)
    raise ValueError(f"unknown upstream {kind!r}")
