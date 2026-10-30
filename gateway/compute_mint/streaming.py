"""Relay a chat-completions SSE stream without weakening what the non-streaming path guarantees.

- Placeholders may be cut between two deltas, so restoring goes through `StreamRestorer`, per content
  and per tool call, and what the client sees is what gets recorded as provenance.
- Provenance is recorded only for a stream that finished: a partial reply is unknown next turn, which fails closed.
- `Relay` settles the ledger however the stream ends (finished, upstream failed, client gone) and always
  closes the upstream connection.
"""
import json
from collections.abc import AsyncIterator, Callable

import anyio
import httpx
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .pricing import Usage
from .vault import StreamRestorer, Vault

DONE = b"data: [DONE]\n\n"
INTERRUPTED = "stream interrupted: client disconnected or gateway stopped; usage as far as known"


class UpstreamStreamError(Exception):
    """The upstream failed after it started streaming (an error event, a bad chunk, an early end)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def sse_json(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def sse_comment(text: str) -> bytes:
    """A comment line: event-stream parsers ignore it, so it cannot break a client."""
    return f": {text}\n\n".encode("utf-8")


async def _sse_events(stream: AsyncIterator[bytes]) -> AsyncIterator[tuple[str, str]]:
    """(event name, data) of each server-sent event. Lines end only at \\n: JSON text may hold U+2028 and the like."""
    buffer, event, data = b"", "", []
    async for piece in stream:
        buffer += piece
        *lines, buffer = buffer.split(b"\n")
        for raw in lines:
            line = raw.rstrip(b"\r").decode("utf-8", "replace")
            if not line:
                if data:
                    yield event, "\n".join(data)
                event, data = "", []
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif line.startswith("event:"):
                event = line[6:].strip()
    if data:
        yield event, "\n".join(data)


def _as_chunk(data: dict) -> dict:
    """A whole completion as one chunk, for an upstream that answered `stream: true` without streaming."""
    choices = []
    for choice in data.get("choices", []):
        delta = dict(choice.get("message") or {})
        if delta.get("tool_calls"):
            delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
        choices.append({"index": choice.get("index", 0), "delta": delta,
                        "finish_reason": choice.get("finish_reason") or "stop"})
    return {**{k: data[k] for k in ("id", "created", "model", "usage") if k in data},
            "object": "chat.completion.chunk", "choices": choices}


async def read_chunks(response: httpx.Response) -> AsyncIterator[dict | None]:
    """Parsed chunks of an upstream response; None stands for `[DONE]`. Raises UpstreamStreamError."""
    if "text/event-stream" not in response.headers.get("content-type", ""):
        try:
            data = json.loads(await response.aread())
        except ValueError:
            raise UpstreamStreamError("upstream_bad_chunk", "upstream sent an unreadable response") from None
        yield _as_chunk(data)
        yield None
        return
    async for event, data in _sse_events(response.aiter_bytes()):
        if data.strip() == "[DONE]":
            yield None
            return
        try:
            chunk = json.loads(data)
        except ValueError:
            raise UpstreamStreamError("upstream_bad_chunk", "upstream sent an unreadable chunk") from None
        if not isinstance(chunk, dict):
            raise UpstreamStreamError("upstream_bad_chunk", "upstream sent an unreadable chunk")
        if event == "error" or chunk.get("error") or chunk.get("type") == "error":
            error = chunk.get("error") if isinstance(chunk.get("error"), dict) else chunk
            raise UpstreamStreamError(str(error.get("code") or "upstream_error"),
                                      str(error.get("message") or "upstream failed during the stream"))
        yield chunk


class _Call:
    def __init__(self, vault: Vault | None) -> None:
        self.id, self.type, self.name, self.arguments = None, "function", "", []
        self.restorer = StreamRestorer(vault)


class _Choice:
    def __init__(self, vault: Vault | None) -> None:
        self.vault = vault
        self.role, self.content, self.finish_reason = "assistant", [], None
        self.restorer = StreamRestorer(vault)
        self.calls: dict[int, _Call] = {}

    def call(self, index: int) -> _Call:
        return self.calls.setdefault(index, _Call(self.vault))


class Assembler:
    """Folds chunks into the messages the client ends up with, restoring placeholders on the way."""

    def __init__(self, vault: Vault | None) -> None:
        self.vault = vault
        self.choices: dict[int, _Choice] = {}
        self.ended = False      # the upstream said [DONE]

    def _choice(self, index: int) -> _Choice:
        return self.choices.setdefault(index, _Choice(self.vault))

    def _flush(self, state: _Choice, delta: dict) -> None:
        held = state.restorer.flush()
        if held:
            delta["content"] = (delta.get("content") or "") + held
            state.content.append(held)
        for index, call in state.calls.items():
            held = call.restorer.flush()
            if held:
                call.arguments.append(held)
                delta.setdefault("tool_calls", []).append({"index": index, "function": {"arguments": held}})

    def feed(self, chunk: dict) -> dict:
        """The chunk with restored text. Text that is held back reappears in a later chunk."""
        for choice in chunk.get("choices") or []:
            state = self._choice(choice.get("index", 0))
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice["delta"] = {}
            state.role = delta.get("role") or state.role
            if isinstance(delta.get("content"), str):
                delta["content"] = state.restorer.feed(delta["content"])
                state.content.append(delta["content"])
            for part in delta.get("tool_calls") or []:
                call = state.call(part.get("index", 0))
                call.id = call.id or part.get("id")
                call.type = part.get("type") or call.type
                fn = part.get("function") or {}
                call.name = call.name or fn.get("name") or ""
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = call.restorer.feed(fn["arguments"])
                    call.arguments.append(fn["arguments"])
            if choice.get("finish_reason"):
                state.finish_reason = choice["finish_reason"]
                self._flush(state, delta)
        return chunk

    def close(self) -> dict | None:
        """A last chunk with whatever is still held back, if anything is."""
        choices = []
        for index, state in self.choices.items():
            delta: dict = {}
            self._flush(state, delta)
            if delta:
                choices.append({"index": index, "delta": delta, "finish_reason": None})
        return {"object": "chat.completion.chunk", "choices": choices} if choices else None

    @property
    def complete(self) -> bool:
        return self.ended or (bool(self.choices) and all(c.finish_reason for c in self.choices.values()))

    @property
    def finish_reason(self) -> str | None:
        return self.choices[0].finish_reason if 0 in self.choices else None

    def messages(self) -> list[dict]:
        out = []
        for _, state in sorted(self.choices.items()):
            message: dict = {"role": state.role, "content": "".join(state.content) or None}
            if state.calls:
                message["tool_calls"] = [
                    {"id": call.id, "type": call.type,
                     "function": {"name": call.name, "arguments": "".join(call.arguments)}}
                    for _, call in sorted(state.calls.items())]
            out.append(message)
        return out


class ChatRenderer:
    """Writes the restored chunks back out as chat-completion chunks."""

    def __init__(self, include_usage: bool) -> None:
        self.include_usage = include_usage      # the gateway always asks upstream for usage; the client may not have

    def start(self) -> list[bytes]:
        return []

    def chunk(self, chunk: dict) -> list[bytes]:
        if not self.include_usage:
            chunk.pop("usage", None)
            if not chunk.get("choices"):
                return []
        return [sse_json(chunk)]

    def replies(self, assembler: Assembler) -> list[dict]:
        return assembler.messages()

    def finish(self, usage: dict | None, row: dict) -> list[bytes]:
        return [sse_comment(cost_comment(row)), DONE]

    def failed(self, code: str, message: str) -> list[bytes]:
        return [sse_json({"error": {"type": "upstream_stream_error", "code": code, "message": message}}), DONE]


def cost_comment(row: dict) -> str:
    return f"x-cm-cost={row['cost']:.6f} x-cm-counterfactual={row['counterfactual']:.6f}"


class Relay(StreamingResponse):
    """Pumps one upstream stream to the client through a renderer.

    `settle(usage, replies, note)` writes the ledger row and the provenance; it runs exactly once. The
    `__call__` wrapper is what guarantees it: when the client goes away Starlette cancels the pump at
    whatever it was waiting for, and nothing inside the pump can be relied on to run.
    """

    def __init__(self, upstream: httpx.Response, renderer, vault: Vault | None,
                 settle: Callable[[Usage, list[dict], str], dict], headers: dict[str, str]) -> None:
        self.upstream, self.renderer, self.settle_with = upstream, renderer, settle
        self.assembler = Assembler(vault)
        self.usage: dict | None = None
        self.settled = False
        super().__init__(self._pump(), media_type="text/event-stream",
                         headers={"cache-control": "no-cache", "x-accel-buffering": "no", **headers})

    def _settle(self, replies: list[dict], note: str) -> dict | None:
        if self.settled:
            return None
        self.settled = True
        return self.settle_with(Usage.from_openai(self.usage), replies, note)

    def _feed(self, chunk: dict) -> list[bytes]:
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        return self.renderer.chunk(self.assembler.feed(chunk))

    async def _pump(self) -> AsyncIterator[bytes]:
        for piece in self.renderer.start():
            yield piece
        failure: UpstreamStreamError | None = None
        try:
            async for chunk in read_chunks(self.upstream):
                if chunk is None:
                    self.assembler.ended = True
                    break
                for piece in self._feed(chunk):
                    yield piece
        except UpstreamStreamError as e:
            failure = e
        except httpx.HTTPError as e:
            failure = UpstreamStreamError("upstream_disconnected", f"upstream connection failed ({type(e).__name__})")
        if failure is None and not self.assembler.complete:
            failure = UpstreamStreamError("upstream_disconnected", "upstream ended the stream before it finished")

        tail = self.assembler.close()
        if tail:
            for piece in self.renderer.chunk(tail):
                yield piece
        if failure is not None:
            self._settle([], f"stream interrupted: {failure.code}; usage as far as known")
            for piece in self.renderer.failed(failure.code, failure.message):
                yield piece
            return
        replies = self.renderer.replies(self.assembler)
        row = self._settle(replies, "")
        for piece in self.renderer.finish(self.usage, row):
            yield piece

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                self._settle([], INTERRUPTED)
                await self.body_iterator.aclose()
                await self.upstream.aclose()
