import json

import httpx
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app
from compute_mint.labels import Label
from compute_mint.policy import Policy, tool_paths

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


def read_file_turn(path: str, content: str) -> list[dict]:
    return [
        {"role": "user", "content": "explain this file"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "r1", "type": "function", "function": {"name": "Read", "arguments": json.dumps({"file_path": path})}}]},
        {"role": "tool", "tool_call_id": "r1", "content": content},
    ]


def test_tool_paths_follow_tool_call_ids():
    msgs = read_file_turn("C:\\repo\\docs\\intro.md", "hello")
    assert tool_paths(msgs) == {2: ["C:/repo/docs/intro.md"]}


def test_unknown_file_is_conservative_and_rules_take_strictest():
    p = Policy()
    msgs = read_file_turn("/repo/docs/intro.md", "hello")
    base = p.baseline_for(msgs, Label.OWN_IP)
    assert base(2, msgs[2]) is Label.CONFIDENTIAL         # no rule yet
    assert base(0, msgs[0]) is Label.OWN_IP               # user message: project default
    p.set_rule("/repo/docs/**", Label.PUBLIC)
    assert p.baseline_for(msgs, Label.OWN_IP)(2, msgs[2]) is Label.PUBLIC
    p.set_rule("/repo/docs/intro.md", Label.CONFIDENTIAL)
    assert p.baseline_for(msgs, Label.OWN_IP)(2, msgs[2]) is Label.CONFIDENTIAL


def _client():
    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                                         "model": body["model"],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})
    app = create_app(Config(api_base="https://mock/v1", api_key="t"), transport=httpx.MockTransport(upstream))
    return TestClient(app)


def test_one_review_decision_moves_future_requests_to_contributor():
    client = _client()
    headers = {"x-cm-project": "own_ip", "x-cm-dial": "own_ip"}
    msgs = read_file_turn("/repo/docs/intro.md", "Intro to our open-source CLI.")

    r1 = client.post("/v1/chat/completions", json={"messages": msgs}, headers={**headers, "x-cm-session": "a"})
    assert r1.headers["x-cm-lane"] == "standard"
    queue = client.get("/v1/review").json()["pending"]
    assert queue[0]["path"] == "/repo/docs/intro.md" and queue[0]["suggested_pattern"] == "/repo/docs/**"

    decided = client.post(f"/v1/review/{queue[0]['id']}", json={"label": "public"}).json()
    assert decided == {"pattern": "/repo/docs/**", "label": "PUBLIC"}
    assert client.get("/v1/review").json()["pending"] == []

    other = read_file_turn("/repo/docs/usage.md", "Usage notes.")
    r2 = client.post("/v1/chat/completions", json={"messages": other}, headers={**headers, "x-cm-session": "b"})
    assert r2.headers["x-cm-lane"] == "contributor"


def test_rules_never_override_the_floor():
    client = _client()
    client.app.state.policy.set_rule("/repo/**", Label.PUBLIC)
    msgs = read_file_turn("/repo/.env", f"API_KEY={KEY}")
    r = client.post("/v1/chat/completions", json={"messages": msgs},
                    headers={"x-cm-project": "public", "x-cm-dial": "public", "x-cm-session": "c"})
    # Credential files are FLOOR as a whole: masking the key is not enough, the rest of the
    # file (hosts, user names, short tokens) must not be contributed either.
    assert r.headers["x-cm-lane"] == "standard"

    readme = read_file_turn("/repo/README.md", f"Set API_KEY={KEY} before running.")
    r2 = client.post("/v1/chat/completions", json={"messages": readme},
                     headers={"x-cm-project": "public", "x-cm-dial": "public", "x-cm-session": "d"})
    # An ordinary public file that mentions a key: the key is masked, the rest is contributable.
    assert r2.headers["x-cm-lane"] == "contributor" and r2.headers["x-cm-masked-spans"] == "1"
