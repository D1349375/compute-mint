import json

import httpx
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


class MockUpstream:
    """Stands in for the Meta Model API. Echoes any placeholder it was sent, like a model would."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        seen = json.dumps(body["messages"], ensure_ascii=False)
        reply = "Rotate ⟨API_KEY_1⟩ and retry." if "⟨API_KEY_1⟩" in seen else "Done."
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20_000, "completion_tokens": 1_000,
                      "prompt_tokens_details": {"cached_tokens": 15_000}},
        })


def make_client():
    upstream = MockUpstream()
    app = create_app(Config(api_base="https://mock/v1", api_key="test"), transport=httpx.MockTransport(upstream))
    return TestClient(app), upstream


def test_secret_never_leaves_and_user_sees_real_value():
    client, upstream = make_client()
    messages = [
        {"role": "user", "content": "deploy fails"},
        {"role": "tool", "tool_call_id": "t", "content": f"401 for token {KEY}"},
    ]
    r = client.post("/v1/chat/completions", json={"model": "any", "messages": messages},
                    headers={"x-cm-session": "s1", "x-cm-project": "public"})
    assert r.status_code == 200
    assert r.headers["x-cm-lane"] == "contributor"
    assert upstream.calls[0]["model"] == "muse-spark-1.3-contributor"
    assert KEY not in json.dumps(upstream.calls[0])
    assert KEY in r.json()["choices"][0]["message"]["content"]


def test_confidential_project_stays_standard_and_ledger_adds_up():
    client, upstream = make_client()
    msgs = [{"role": "user", "content": "summarise our unreleased plan"}]
    r = client.post("/v1/chat/completions", json={"model": "any", "messages": msgs},
                    headers={"x-cm-session": "s2", "x-cm-project": "confidential", "x-cm-dial": "own_ip"})
    assert r.headers["x-cm-lane"] == "standard"
    assert upstream.calls[0]["model"] == "muse-spark-1.3"

    client.post("/v1/chat/completions", json={"model": "any", "messages": [{"role": "user", "content": "explain quicksort"}]},
                headers={"x-cm-session": "s3", "x-cm-project": "public"})
    s = client.get("/v1/ledger/summary").json()
    assert s["requests"] == 2
    assert round(s["counterfactual_usd"], 5) == round(2 * 0.01275, 5)
    assert round(s["spent_usd"], 5) == round(0.01275 + 0.00073, 5)
    assert 0.49 < s["contributable_token_share"] < 0.51


def test_streaming_rejected_for_now():
    client, _ = make_client()
    r = client.post("/v1/chat/completions", json={"model": "any", "stream": True,
                                                  "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
