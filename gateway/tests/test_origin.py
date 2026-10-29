import json
import random
import string

import httpx
import pytest
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app
from compute_mint.context import Provenance
from compute_mint.labels import Label
from compute_mint.origin import (NON_CONTRIBUTOR, Origin, OriginTracker, blocking_origin, message_origins,
                                 origin_allows_contributor, parse_client)
from compute_mint.router import CONTRIBUTOR, STANDARD, route
from compute_mint.vault import Vault


def _route(msgs, prov=None, origins=None, dial=Label.OWN_IP, baseline=Label.PUBLIC):
    return route(msgs, baseline=baseline, dial=dial, vault=Vault(), provenance=prov or Provenance(), origins=origins)


def test_only_foreign_model_origins_are_blocked():
    assert set(NON_CONTRIBUTOR) == {Origin.ANTHROPIC, Origin.OPENAI, Origin.UNKNOWN_MODEL}
    for o in Origin:
        assert origin_allows_contributor(o) == (o not in NON_CONTRIBUTOR)


def test_origin_of_each_role():
    prov = Provenance()
    ours = {"role": "assistant", "content": "from the gateway"}
    prov.record(ours, Label.PUBLIC)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "tool", "tool_call_id": "t", "content": "t"}, ours,
            {"role": "assistant", "content": "someone else wrote this"}]
    assert message_origins(msgs, prov) == [Origin.USER, Origin.USER, Origin.TOOL, Origin.META, Origin.UNKNOWN_MODEL]
    assert message_origins(msgs, prov, Origin.ANTHROPIC)[-1] is Origin.ANTHROPIC
    assert message_origins(msgs, prov, Origin.OPENAI)[-1] is Origin.OPENAI


def test_client_header_parsing_and_cannot_loosen():
    assert parse_client(None) is None
    assert parse_client("Anthropic") is Origin.ANTHROPIC
    assert parse_client("openai") is Origin.OPENAI
    for bad in ["meta", "local", "user", "claude"]:
        with pytest.raises(ValueError):
            parse_client(bad)
    with pytest.raises(ValueError):
        message_origins([{"role": "assistant", "content": "x"}], Provenance(), Origin.META)


def test_foreign_assistant_message_keeps_public_request_off_contributor():
    msgs = [{"role": "user", "content": "explain quicksort"},
            {"role": "assistant", "content": "Quicksort picks a pivot."},
            {"role": "user", "content": "now mergesort"}]
    d = _route(msgs)
    assert d.lane == STANDARD and d.blocked_by == [1] and "by origin" in d.reason
    assert _route(msgs[:1]).lane == CONTRIBUTOR


def test_explicit_origins_override_and_standard_gets_unmodified_messages():
    msgs = [{"role": "user", "content": "fixed template"}, {"role": "user", "content": "free text from a model"}]
    d = _route(msgs, origins=[Origin.USER, Origin.ANTHROPIC])
    assert d.lane == STANDARD and d.blocked_by == [1]
    assert _route(msgs, origins=[Origin.USER, Origin.PUBLIC_SOURCE]).lane == CONTRIBUTOR


def test_standard_reply_derived_from_foreign_output_stays_off_contributor():
    prov, tracker = Provenance(), OriginTracker()
    claude = {"role": "assistant", "content": "the plan is X"}
    ctx = [{"role": "user", "content": "plan?"}, claude]
    origins = tracker.of_messages(ctx, prov, Origin.ANTHROPIC)
    assert _route(ctx, prov, origins).lane == STANDARD
    reply = {"role": "assistant", "content": "Meta's paraphrase of X"}
    prov.record(reply, Label.PUBLIC)
    tracker.record_reply(reply, origins)

    # The reply is ours, but it derives from Claude output, so a request holding only it is blocked too.
    later = [{"role": "user", "content": "go on"}, reply]
    o2 = tracker.of_messages(later, prov)
    assert o2 == [Origin.USER, Origin.ANTHROPIC] and blocking_origin(o2) is Origin.ANTHROPIC
    assert _route(later, prov, o2).lane == STANDARD
    # A reply generated from a clean context is plain META and fine.
    clean = {"role": "assistant", "content": "clean answer"}
    prov.record(clean, Label.PUBLIC)
    tracker.record_reply(clean, [Origin.USER])
    assert _route([later[0], clean], prov, tracker.of_messages([later[0], clean], prov)).lane == CONTRIBUTOR


def _words(rng: random.Random, tag: str) -> str:
    return tag + "".join(rng.choice(string.ascii_lowercase) for _ in range(16))


def test_property_foreign_origin_content_never_reaches_contributor():
    """Simulates multi-step sessions. The oracle tracks which texts truly derive from foreign output."""
    rng = random.Random(11)
    contributor_requests = 0
    for _ in range(400):
        prov, tracker = Provenance(), OriginTracker()
        client = rng.choice([None, Origin.ANTHROPIC, Origin.OPENAI, Origin.UNKNOWN_MODEL])
        tainted_texts: set[str] = set()
        history: list[dict] = []
        for _step in range(rng.randrange(1, 7)):
            kind = rng.choice(["user", "tool", "foreign", "foreign"])
            text = _words(rng, kind[:3])
            if kind == "foreign":
                history.append({"role": "assistant", "content": text})
                tainted_texts.add(text)
            else:
                role = "tool" if kind == "tool" else "user"
                m = {"role": role, "content": text}
                if role == "tool":
                    m["tool_call_id"] = "x"
                history.append(m)

            origins = tracker.of_messages(history, prov, client)
            d = route(history, baseline=Label.PUBLIC, dial=rng.choice([Label.PUBLIC, Label.OWN_IP]),
                      vault=Vault(), provenance=prov, origins=origins)
            if d.lane == CONTRIBUTOR:
                contributor_requests += 1
                sent = json.dumps(d.messages)
                assert not any(t in sent for t in tainted_texts)
            # The gateway answers; that reply derives from foreign output iff the context held any.
            reply_text = _words(rng, "met")
            reply = {"role": "assistant", "content": reply_text}
            prov.record(reply, Label.PUBLIC)
            tracker.record_reply(reply, origins)
            if any(m["content"] in tainted_texts for m in history):
                tainted_texts.add(reply_text)
            history.append(reply)
    assert contributor_requests > 50  # the property is not vacuous


# ---- through the HTTP gateway ----

class Upstream:
    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        return httpx.Response(200, json={
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10}})


def _client():
    up = Upstream()
    return TestClient(create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), httpx.MockTransport(up))), up


@pytest.mark.parametrize("client_value", ["anthropic", "openai", None])
def test_gateway_keeps_agent_authored_history_on_standard(client_value):
    client, up = _client()
    headers = {"x-cm-session": "s", "x-cm-project": "public"}
    if client_value:
        headers["x-cm-client"] = client_value
    msgs = [{"role": "user", "content": "explain quicksort"},
            {"role": "assistant", "content": "It picks a pivot."},
            {"role": "user", "content": "and mergesort?"}]
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": msgs}, headers=headers)
    assert r.headers["x-cm-lane"] == "standard" and up.calls[0]["model"] == "muse-spark-1.3"
    # Without foreign assistant messages the same project stays on Contributor.
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": msgs[:1]},
                    headers={**headers, "x-cm-session": "s2"})
    assert r.headers["x-cm-lane"] == "contributor"


def test_gateway_reply_is_meta_but_taint_from_standard_context_carries():
    client, up = _client()
    h = {"x-cm-session": "s", "x-cm-project": "public", "x-cm-client": "anthropic"}
    first = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "foreign line"}]
    r1 = client.post("/v1/chat/completions", json={"model": "m", "messages": first}, headers=h)
    reply = r1.json()["choices"][0]["message"]
    assert r1.headers["x-cm-lane"] == "standard"
    r2 = client.post("/v1/chat/completions",
                     json={"model": "m", "messages": [{"role": "user", "content": "q2"}, reply]}, headers=h)
    assert r2.headers["x-cm-lane"] == "standard"    # derived from Anthropic-origin output

    r3 = client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "fresh"}]},
                     headers={**h, "x-cm-session": "t"})
    reply3 = r3.json()["choices"][0]["message"]
    assert r3.headers["x-cm-lane"] == "contributor"
    r4 = client.post("/v1/chat/completions", headers={**h, "x-cm-session": "t"}, json={
        "model": "m", "messages": [{"role": "user", "content": "fresh"}, reply3, {"role": "user", "content": "more"}]})
    assert r4.headers["x-cm-lane"] == "contributor"     # our own clean Meta reply is fine


def test_bad_client_header_is_rejected():
    client, up = _client()
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                    headers={"x-cm-client": "meta"})
    assert r.status_code == 400 and up.calls == []
