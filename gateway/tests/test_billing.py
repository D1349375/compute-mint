"""Billing mode. On promotional credits every Meta request is non-paid (ToS §13.3, §6), so the
Standard lane is not private: what may not go to Contributor must not reach Meta at all."""
import asyncio
import json
import os
import random
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app
from compute_mint.billing import parse_billing
from compute_mint.delegate import DelegateConfig, Delegator
from compute_mint.ledger import Ledger
from compute_mint.origin import Origin

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
META_HOST, LOCAL_HOST = "mock", "local"


class Hosts:
    """Mock Meta API and mock local server on one transport, told apart by host."""

    def __init__(self) -> None:
        self.calls: dict[str, list[dict]] = {META_HOST: [], LOCAL_HOST: []}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls[request.url.host].append(body)
        return httpx.Response(200, json={
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20_000, "completion_tokens": 1_000,
                      "prompt_tokens_details": {"cached_tokens": 15_000}}})


def make_client(billing: str, local: bool = False):
    hosts = Hosts()
    config = Config(api_base=f"https://{META_HOST}/v1", api_key="t", billing=billing,
                    local_api_base=f"http://{LOCAL_HOST}/v1" if local else "")
    return TestClient(create_app(config, transport=httpx.MockTransport(hosts))), hosts


CONFIDENTIAL = {"x-cm-session": "c", "x-cm-project": "confidential", "x-cm-dial": "own_ip"}
ASK = {"model": "any", "messages": [{"role": "user", "content": "summarise our unreleased plan"}]}


def test_credits_hold_back_what_paid_billing_sends_to_standard():
    client, hosts = make_client("paid")
    assert client.post("/v1/chat/completions", json=ASK, headers=CONFIDENTIAL).headers["x-cm-lane"] == "standard"

    client, hosts = make_client("credits")
    r = client.post("/v1/chat/completions", json=ASK, headers=CONFIDENTIAL)
    assert r.status_code == 403
    assert r.headers["x-cm-lane"] == "held" and r.headers["x-cm-billing"] == "credits"
    assert r.json()["error"]["code"] == "not_contributable_on_credits"
    assert "§13.3" in r.json()["error"]["message"]
    assert hosts.calls[META_HOST] == []
    s = client.get("/v1/ledger/summary").json()
    assert s["requests"] == 1 and s["held_requests"] == 1 and s["spent_usd"] == 0


def test_credits_still_send_contributable_work_and_count_credit_spend():
    client, hosts = make_client("credits")
    r = client.post("/v1/chat/completions", headers={"x-cm-session": "p", "x-cm-project": "public"},
                    json={"model": "any", "messages": [{"role": "user", "content": "explain quicksort"}]})
    assert r.status_code == 200 and r.headers["x-cm-lane"] == "contributor"
    assert hosts.calls[META_HOST][0]["model"] == "muse-spark-1.3-contributor"
    s = client.get("/v1/ledger/summary").json()
    assert s["credits_usd"] == pytest.approx(s["spent_usd"]) and s["credits_usd"] > 0


def test_credits_with_local_model_keep_confidential_work_on_this_machine():
    client, hosts = make_client("credits", local=True)
    r = client.post("/v1/chat/completions", json=ASK, headers=CONFIDENTIAL)
    assert r.status_code == 200 and r.headers["x-cm-lane"] == "local"
    assert hosts.calls[META_HOST] == []
    sent = hosts.calls[LOCAL_HOST][0]
    assert sent["model"] == "muse-glimmer" and sent["messages"][0]["content"] == "summarise our unreleased plan"
    row = client.app.state.ledger.db.execute("SELECT cost, counterfactual, billing FROM requests").fetchone()
    assert row[0] == 0 and row[1] == pytest.approx(0.01275) and row[2] == "credits"


def test_agent_authored_history_does_not_reach_meta_on_credits():
    # Claude/GPT output may not train Meta models; on credits even Standard would.
    client, hosts = make_client("credits")
    msgs = [{"role": "user", "content": "explain quicksort"},
            {"role": "assistant", "content": "It picks a pivot."},
            {"role": "user", "content": "and mergesort?"}]
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": msgs},
                    headers={"x-cm-session": "a", "x-cm-project": "public", "x-cm-client": "anthropic"})
    assert r.headers["x-cm-lane"] == "held" and hosts.calls[META_HOST] == []


def test_on_credits_every_meta_request_is_a_clean_contributor_request():
    rng = random.Random(11)
    client, hosts = make_client("credits")
    lanes = set()
    for i in range(120):
        project = rng.choice(["public", "own_ip", "confidential"])
        msgs = [{"role": "user", "content": rng.choice(["fix the parser", "summarise the roadmap"])}]
        if rng.random() < 0.5:
            msgs.append({"role": "tool", "tool_call_id": "t", "content": f"401 for token {KEY}"})
        if rng.random() < 0.3:
            msgs.append({"role": "assistant", "content": "earlier answer"})
        headers = {"x-cm-session": f"s{i}", "x-cm-project": project,
                   "x-cm-dial": rng.choice(["public", "own_ip"]),
                   "x-cm-client": rng.choice(["anthropic", "openai", "unknown"])}
        r = client.post("/v1/chat/completions", json={"model": "m", "messages": msgs}, headers=headers)
        lanes.add(r.headers["x-cm-lane"])
    assert lanes == {"contributor", "held"}
    assert hosts.calls[META_HOST]
    for body in hosts.calls[META_HOST]:
        assert body["model"] == "muse-spark-1.3-contributor"
        assert KEY not in json.dumps(body)


def test_billing_is_validated_and_defaults_to_credits():
    with pytest.raises(ValueError):
        parse_billing("free")
    with pytest.raises(ValueError):
        create_app(Config(billing="prepaid"))
    with pytest.raises(ValueError):
        DelegateConfig(caller=Origin.ANTHROPIC, billing="")
    if "CM_BILLING" not in os.environ:
        assert Config().billing == "credits"
        assert DelegateConfig(caller=Origin.ANTHROPIC).billing == "credits"


class Upstream:
    def __init__(self):
        self.calls = []

    async def __call__(self, model, messages):
        self.calls.append((model, messages))
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}],
                "usage": {"prompt_tokens": 2000, "completion_tokens": 100}}


class Fetcher:
    def file(self, ref):
        return "Public changelog: version 2 ships Friday."


def test_delegate_free_text_is_held_or_local_on_credits():
    meta, local, ledger = Upstream(), Upstream(), Ledger()
    cfg = DelegateConfig(api_base="x", api_key="x", caller=Origin.ANTHROPIC, billing="credits")
    out = asyncio.run(Delegator(Fetcher(), meta, cfg, ledger).delegate("summarize", ["notes.md"], instruction="be terse"))
    assert out["lane"] == "held" and out["result"] is None and "§13.3" in out["note"]
    assert meta.calls == []
    # Without free text the same task is contributable and goes out.
    out = asyncio.run(Delegator(Fetcher(), meta, cfg, ledger).delegate("summarize", ["notes.md"]))
    assert out["lane"] == "contributor" and meta.calls[0][0] == "muse-spark-1.3-contributor"

    out = asyncio.run(Delegator(Fetcher(), meta, cfg, ledger, local=local)
                      .delegate("summarize", ["notes.md"], instruction="be terse"))
    assert out["lane"] == "local" and out["cost_usd"] == 0 and len(meta.calls) == 1
    assert local.calls[0][1][-1]["content"] == "be terse"
    assert ledger.summary()["held_requests"] == 1 and ledger.summary()["local_requests"] == 1


def test_old_ledger_file_gains_billing_column(tmp_path):
    path = tmp_path / "ledger.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, session TEXT NOT NULL,"
               " lane TEXT NOT NULL, model TEXT NOT NULL, context_label INTEGER NOT NULL,"
               " prompt_tokens INTEGER NOT NULL, cached_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,"
               " cost REAL NOT NULL, counterfactual REAL NOT NULL, masked_spans INTEGER NOT NULL, reason TEXT NOT NULL,"
               " sent_payload TEXT, chars_in INTEGER NOT NULL DEFAULT 0, chars_out INTEGER NOT NULL DEFAULT 0)")
    db.execute("INSERT INTO requests (ts, session, lane, model, context_label, prompt_tokens, cached_tokens,"
               " completion_tokens, cost, counterfactual, masked_spans, reason) VALUES (0,'s','standard','m',0,1,0,1,1,1,0,'')")
    db.commit()
    db.close()
    ledger = Ledger(path)
    assert ledger.db.execute("SELECT billing FROM requests").fetchone()[0] == "paid"
    assert ledger.summary()["credits_usd"] == 0
