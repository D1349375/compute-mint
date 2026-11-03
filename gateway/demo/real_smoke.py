"""Smoke test of the gateway against the real Meta Model API (invented prompts only).

    cd gateway
    python -m demo.real_smoke [--out smoke.json]

Reads META_API_KEY / META_API_BASE from ../.env (never printed). Starts the gateway on a local port
(real sockets, so streaming is really streamed) and sends one request per case: Contributor and Standard,
streaming and not, plus a masked secret that must come back restored. Every prompt is made up here.
Contributor cases run on credits, as in production; Standard cases need `paid` routing and exist only
because the data is invented (on credits the gateway refuses to send anything non-contributable to Meta).
"""
import argparse
import json
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from compute_mint.envfile import load_env_file

load_env_file(Path(__file__).resolve().parents[2] / ".env")

from compute_mint.app import Config, create_app   # noqa: E402  (after the environment is loaded)

FAKE_KEY = "sk-" + "smoke" + "K4mP9xT2vB7nQ5wL8cR3dF6h"   # invented, built at run time
CONTRIBUTOR_HEADERS = {"x-cm-project": "public", "x-cm-dial": "public"}
STANDARD_HEADERS = {"x-cm-project": "confidential"}
TOOLS = [{"type": "function", "function": {
    "name": "save_note", "description": "Save a note.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}]


def serve(app) -> tuple[str, uvicorn.Server]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


def parse_sse(raw: str) -> dict:
    events, comments, content, tool_args, usage, finish = [], [], "", {}, None, None
    for block in raw.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith(":"):
                comments.append(line)
            elif line.startswith("data:"):
                events.append(line[5:].strip())
    chunks = 0
    for e in events:
        if e == "[DONE]":
            continue
        d = json.loads(e)
        chunks += 1
        usage = d.get("usage") or usage
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or {}
            content += delta.get("content") or ""
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                tool_args[i] = tool_args.get(i, "") + (tc.get("function") or {}).get("arguments", "")
            finish = ch.get("finish_reason") or finish
    return {"chunks": chunks, "done": events[-1:] == ["[DONE]"], "comments": comments, "content": content,
            "tool_args": list(tool_args.values()), "usage": usage, "finish": finish}


def case(base: str, name: str, kind: str, headers: dict, messages: list[dict], stream: bool, tools=None) -> dict:
    body = {"model": "x", "messages": messages, "max_tokens": 4000, "stream": stream}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if tools:
        body["tools"] = tools
    t0 = time.time()
    out = {"case": name, "kind": kind, "stream": stream}
    with httpx.Client(base_url=base, timeout=300) as c:
        r = c.post("/v1/chat/completions", json=body, headers={"x-cm-session": f"smoke-{name}", **headers})
    out["status"], out["seconds"] = r.status_code, round(time.time() - t0, 1)
    out["lane"] = r.headers.get("x-cm-lane")
    if r.status_code != 200:
        out["error"] = r.text[:500]
        return out
    if stream:
        out.update(parse_sse(r.text))
        out["content_type"] = r.headers.get("content-type")
    else:
        d = r.json()
        msg = d["choices"][0]["message"]
        out.update(content=msg.get("content") or "",
                   tool_args=[c["function"]["arguments"] for c in msg.get("tool_calls") or []],
                   usage=d.get("usage"), finish=d["choices"][0].get("finish_reason"), model=d.get("model"),
                   cost_header=r.headers.get("x-cm-cost"))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="")
    args = p.parse_args()
    key = os.environ.get("META_API_KEY")
    if not key:
        raise SystemExit("META_API_KEY is not set (put it in .env)")
    base_url = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")

    credits = create_app(Config(api_base=base_url, api_key=key, billing="credits"))
    paid = create_app(Config(api_base=base_url, api_key=key, billing="paid"))
    credits_url, s1 = serve(credits)
    paid_url, s2 = serve(paid)

    plain = [{"role": "user", "content": "Reply with exactly one word: pong"}]
    secret = [{"role": "user", "content": "Copy this token exactly into a JSON object {\"token\": \"...\"} and reply "
                                          f"with only that object: {FAKE_KEY}"}]
    tool = [{"role": "user", "content": f"Call save_note once with text set to exactly this token: {FAKE_KEY}"}]
    results = [
        case(credits_url, "contributor-plain", "contributor", CONTRIBUTOR_HEADERS, plain, False),
        case(credits_url, "contributor-plain-stream", "contributor", CONTRIBUTOR_HEADERS, plain, True),
        case(paid_url, "standard-plain", "standard", STANDARD_HEADERS, plain, False),
        case(paid_url, "standard-plain-stream", "standard", STANDARD_HEADERS, plain, True),
        case(credits_url, "contributor-secret", "contributor", CONTRIBUTOR_HEADERS, secret, False),
        case(credits_url, "contributor-secret-stream", "contributor", CONTRIBUTOR_HEADERS, secret, True),
        case(credits_url, "contributor-tool", "contributor", CONTRIBUTOR_HEADERS, tool, False, TOOLS),
        case(credits_url, "contributor-tool-stream", "contributor", CONTRIBUTOR_HEADERS, tool, True, TOOLS),
        case(credits_url, "standard-on-credits", "standard", STANDARD_HEADERS, plain, False),
    ]
    for r in results:
        r["secret_restored"] = FAKE_KEY in (r.get("content") or "") or any(FAKE_KEY in a for a in r.get("tool_args") or [])
    ledgers = {}
    for name, app in (("credits", credits), ("paid", paid)):
        rows = app.state.ledger.db.execute(
            "SELECT session, lane, model, prompt_tokens, cached_tokens, completion_tokens, cost, counterfactual, "
            "masked_spans, sent_payload, billing FROM requests ORDER BY id").fetchall()
        ledgers[name] = [{"session": r[0], "lane": r[1], "model": r[2], "prompt": r[3], "cached": r[4],
                          "completion": r[5], "cost": r[6], "counterfactual": r[7], "masked_spans": r[8],
                          "billing": r[10], "key_in_sent_payload": FAKE_KEY in (r[9] or ""),
                          "placeholder_in_sent_payload": "⟨" in (r[9] or "")} for r in rows]
    s1.should_exit = s2.should_exit = True
    text = json.dumps({"results": results, "ledger": ledgers}, ensure_ascii=False, indent=1).replace(key, "<redacted>")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
