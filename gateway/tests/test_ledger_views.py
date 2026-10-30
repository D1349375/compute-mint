"""Read-only ledger views for the dashboard: per-request rows, sessions and the gateway's billing status."""
import json

import httpx
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2_000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1_000}}})


def make_client(billing="credits", local=False):
    config = Config(api_base="https://mock/v1", api_key="t", billing=billing,
                    local_api_base="http://local/v1" if local else "")
    return TestClient(create_app(config, transport=httpx.MockTransport(ok)))


def send(client, session, project, content):
    return client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": content}]},
                       headers={"x-cm-session": session, "x-cm-project": project, "x-cm-dial": "own_ip"})


def test_requests_lists_rows_newest_first_with_reasons_and_label_names():
    client = make_client()
    send(client, "a", "public", f"deploy fails: 401 for token {KEY}")
    send(client, "b", "confidential", "summarise our unreleased plan")
    page = client.get("/v1/ledger/requests").json()
    assert page["total"] == 2 and page["offset"] == 0
    held, contrib = page["requests"]
    assert held["lane"] == "held" and held["session"] == "b" and "§13.3" in held["reason"]
    assert held["context_label"] == "CONFIDENTIAL" and held["has_payload"] is False
    assert contrib["lane"] == "contributor" and contrib["masked_spans"] == 1 and contrib["has_payload"] is True
    assert contrib["billing"] == "credits" and contrib["cost"] > 0
    assert "sent_payload" not in contrib          # only on request


def test_payload_is_the_masked_text_that_left_and_filters_page():
    client = make_client()
    send(client, "a", "public", f"deploy fails: 401 for token {KEY}")
    for i in range(4):
        send(client, "b", "public", f"explain step {i}")
    page = client.get("/v1/ledger/requests", params={"session": "a", "payload": "true"}).json()
    assert page["total"] == 1
    sent = page["requests"][0]["sent_payload"]
    assert "⟨API_KEY_1⟩" in sent and KEY not in sent
    assert json.loads(sent)[0]["role"] == "user"

    page = client.get("/v1/ledger/requests", params={"session": "b", "limit": 2, "offset": 1}).json()
    assert page["total"] == 4 and len(page["requests"]) == 2
    assert page["requests"][0]["id"] > page["requests"][1]["id"]
    assert client.get("/v1/ledger/requests", params={"lane": "held"}).json()["total"] == 0
    assert client.get("/v1/ledger/requests", params={"lane": "contributor"}).json()["total"] == 5


def test_one_request_with_its_payload():
    client = make_client()
    send(client, "a", "public", f"deploy fails: 401 for token {KEY}")
    send(client, "b", "confidential", "summarise our unreleased plan")
    row = client.get("/v1/ledger/requests/1").json()
    assert row["lane"] == "contributor" and row["context_label"] == "PUBLIC"
    assert "⟨API_KEY_1⟩" in row["sent_payload"] and KEY not in row["sent_payload"]
    held = client.get("/v1/ledger/requests/2").json()
    assert held["lane"] == "held" and held["sent_payload"] is None and held["has_payload"] is False
    assert client.get("/v1/ledger/requests/99").status_code == 404


def test_requests_rejects_bad_parameters():
    client = make_client()
    assert client.get("/v1/ledger/requests", params={"lane": "meta"}).status_code == 400
    assert client.get("/v1/ledger/requests", params={"limit": 0}).status_code == 400
    assert client.get("/v1/ledger/requests", params={"limit": 501}).status_code == 400
    assert client.get("/v1/ledger/requests", params={"offset": -1}).status_code == 400


def test_sessions_and_status():
    client = make_client(local=True)
    send(client, "a", "public", "explain quicksort")
    send(client, "b", "confidential", "summarise our unreleased plan")
    send(client, "a", "public", "and mergesort")
    sessions = client.get("/v1/ledger/sessions").json()["sessions"]
    assert [s["session"] for s in sessions] == ["a", "b"]
    assert sessions[0]["requests"] == 2 and sessions[1]["spent_usd"] == 0 and sessions[1]["counterfactual_usd"] > 0
    assert client.get("/v1/status").json() == {"billing": "credits", "local_model": "muse-glimmer",
                                               "contributor_model": "muse-spark-1.3-contributor",
                                               "standard_model": "muse-spark-1.3"}
    assert make_client("paid").get("/v1/status").json()["local_model"] is None


def test_views_do_not_write_to_the_ledger():
    client = make_client()
    send(client, "a", "public", "explain quicksort")
    before = client.get("/v1/ledger/summary").json()
    for path in ("/v1/ledger/requests", "/v1/ledger/requests/1", "/v1/ledger/sessions", "/v1/status"):
        client.get(path)
    assert client.get("/v1/ledger/summary").json() == before
