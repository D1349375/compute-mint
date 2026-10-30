"""A scripted chat-completions upstream that streams, and helpers to read what the gateway streams back."""
import asyncio
import json
import random

import httpx

USAGE = {"prompt_tokens": 20_000, "completion_tokens": 1_000, "prompt_tokens_details": {"cached_tokens": 15_000}}


class Script(httpx.AsyncByteStream):
    """The body of one upstream response. Knows whether the gateway closed it."""

    def __init__(self, pieces: list[bytes], fail: Exception | None = None, hang: bool = False) -> None:
        self.pieces, self.fail, self.hang = pieces, fail, hang
        self.closed = False

    async def __aiter__(self):
        for piece in self.pieces:
            yield piece
        if self.fail:
            raise self.fail
        if self.hang:
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def cuts(text: str, rng: random.Random, most: int = 6) -> list[str]:
    """`text` cut at random places: any place, placeholders included."""
    points = sorted(rng.sample(range(1, len(text)), min(rng.randrange(0, most), len(text) - 1))) if len(text) > 1 else []
    return [text[a:b] for a, b in zip([0, *points], [*points, len(text)])]


def frame(chunk: dict) -> bytes:
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")


def reply_chunks(text: str | None = None, calls: list[dict] | None = None, *, usage: dict | None = USAGE,
                 finish: str | None = None, rng: random.Random | None = None, done: bool = True,
                 model: str = "m") -> list[dict]:
    """A reply as chat-completion chunks. `calls` are {"id", "name", "arguments"}."""
    rng = rng or random.Random(0)
    base = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": model}
    out = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}]
    for piece in cuts(text, rng) if text else []:
        out.append({**base, "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
    for i, call in enumerate(calls or []):
        first = {"index": i, "id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": ""}}
        out.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [first]}, "finish_reason": None}]})
        for piece in cuts(call["arguments"], rng) if call["arguments"] else []:
            part = {"index": i, "function": {"arguments": piece}}
            out.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [part]}, "finish_reason": None}]})
    if done:
        reason = finish or ("tool_calls" if calls else "stop")
        out.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]})
        if usage:
            out.append({**base, "choices": [], "usage": usage})
    return out


def sse_bytes(chunks: list[dict], *, rng: random.Random | None = None, done: bool = True) -> list[bytes]:
    """Chunks on the wire; with `rng`, split at arbitrary bytes (a multi-byte character may be cut too)."""
    raw = b"".join(frame(c) for c in chunks) + (b"data: [DONE]\n\n" if done else b"")
    if not rng:
        return [raw]
    points = sorted(rng.sample(range(1, len(raw)), min(40, len(raw) - 1)))
    return [raw[a:b] for a, b in zip([0, *points], [*points, len(raw)])]


class Upstream:
    """Mock Meta API and mock local server on one transport, told apart by host.

    `next` holds what the next requests answer: a list of byte pieces, a Script, an httpx.Response or an
    exception. With nothing queued, it streams `default_text` to a streaming request and answers a plain
    completion otherwise.
    """

    def __init__(self, default_text: str = "ok") -> None:
        self.calls: list[dict] = []
        self.hosts: list[str] = []
        self.next: list = []
        self.scripts: list[Script] = []
        self.default_text = default_text

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        self.hosts.append(request.url.host)
        planned = self.next.pop(0) if self.next else None
        if isinstance(planned, Exception):
            raise planned
        if isinstance(planned, httpx.Response):
            return planned
        if planned is None and not body.get("stream"):
            return httpx.Response(200, json={
                "id": "x", "object": "chat.completion", "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": self.default_text},
                             "finish_reason": "stop"}], "usage": USAGE})
        if planned is None:
            planned = sse_bytes(reply_chunks(self.default_text, model=body["model"]))
        script = planned if isinstance(planned, Script) else Script(planned)
        self.scripts.append(script)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=script)


def parse_sse(text: str) -> list[tuple[str, str]]:
    """(event, data) of each event in a response body. Comments are dropped, as a client does."""
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event, data = "", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
        if data:
            out.append((event, "\n".join(data)))
    return out


def chat_message(text: str) -> tuple[dict, list[dict]]:
    """What an OpenAI-style client assembles from a chat stream: (message, chunks)."""
    chunks = [json.loads(d) for _, d in parse_sse(text) if d != "[DONE]"]
    message: dict = {"role": "assistant", "content": ""}
    calls: dict[int, dict] = {}
    for chunk in chunks:
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            message["content"] += delta.get("content") or ""
            for part in delta.get("tool_calls") or []:
                call = calls.setdefault(part["index"], {"id": None, "type": "function",
                                                        "function": {"name": "", "arguments": ""}})
                call["id"] = part.get("id") or call["id"]
                fn = part.get("function") or {}
                call["function"]["name"] += fn.get("name") or ""
                call["function"]["arguments"] += fn.get("arguments") or ""
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return message, chunks


async def drive_asgi(app, path: str, body: dict, headers: dict[str, str], *, disconnect_after: int = 1,
                     raise_on_send: bool = False) -> list[dict]:
    """Run one request through the ASGI app; the client goes away after `disconnect_after` body messages."""
    sent: list[dict] = []
    gone = asyncio.Event()
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if raise_on_send and gone.is_set():
            raise OSError("client went away")
        sent.append(message)
        if sum(m["type"] == "http.response.body" and bool(m.get("body")) for m in sent) >= disconnect_after:
            gone.set()

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"content-type", b"application/json")]
                        + [(k.encode(), v.encode()) for k, v in headers.items()],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}
    await asyncio.wait_for(app(scope, receive, send), 10)
    return sent
