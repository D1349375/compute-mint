"""stream: true on /v1/chat/completions keeps every guarantee of the non-streaming path."""
import asyncio
import json
import random
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from upstream_sim import USAGE, Script, Upstream, chat_message, cuts, drive_asgi, frame, parse_sse, reply_chunks, sse_bytes

from compute_mint.app import Config, create_app
from compute_mint.context import fingerprint
from compute_mint.vault import StreamRestorer, Vault

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
OTHER = "sk-" + "z9Y8x7W6v5U4t3S2r1Q0p9O8"
MAIL = "lin" + "@quill-" + "mail.test"
PUBLIC = {"x-cm-session": "s", "x-cm-project": "public"}


def make(billing="paid", local=False, default_text="ok"):
    up = Upstream(default_text)
    config = Config(api_base="https://mock/v1", api_key="t", billing=billing,
                    local_api_base="http://local/v1" if local else "")
    app = create_app(config, transport=httpx.MockTransport(up))
    return TestClient(app), up


def ask(text="explain quicksort", **extra):
    return {"model": "any", "stream": True, "messages": [{"role": "user", "content": text}], **extra}


def with_secret():
    return ask(f"401 for token {KEY}, and {OTHER}, ask {MAIL}")


def rows(client):
    columns = ("lane", "prompt_tokens", "cached_tokens", "completion_tokens", "cost", "reason", "sent_payload")
    cur = client.app.state.ledger.db.execute(f"SELECT {', '.join(columns)} FROM requests ORDER BY id")
    return [dict(zip(columns, r)) for r in cur.fetchall()]


# ---- restoring placeholders ------------------------------------------------------------------------

def _vault():
    vault = Vault()
    vault.mask(f"{KEY} {OTHER} {MAIL}")
    for i in range(3, 12):      # ⟨API_KEY_1⟩ is a prefix-sharing neighbour of ⟨API_KEY_10⟩
        vault.mask("sk-" + f"{i:02d}" + "q" * 24)
    return vault


def test_restoring_gives_the_same_text_for_any_split():
    rng = random.Random(7)
    vault = _vault()
    atoms = ["⟨API_KEY_1⟩", "⟨API_KEY_10⟩", "⟨API_KEY_2⟩", "⟨EMAIL_1⟩", "⟨UNKNOWN_9⟩", "⟨", "⟩", "⟨API_", "⟨API_KEY_1",
             "⟨⟨API_KEY_1⟩", "plain ", "⟨a⟩", "⟨API_KEY_99⟩", "日本語", "\n", "⟨API_KEY_1⟩⟨API_KEY_2⟩"]
    for _ in range(3000):
        text = "".join(rng.choice(atoms) for _ in range(rng.randrange(1, 9)))
        restorer = StreamRestorer(vault)
        out = "".join(restorer.feed(piece) for piece in cuts(text, rng, most=9)) + restorer.flush()
        assert out == vault.rehydrate(text), text


def test_nothing_is_held_back_that_cannot_become_a_placeholder():
    vault = _vault()
    restorer = StreamRestorer(vault)
    assert restorer.feed("a ⟨ZZZ") == "a ⟨ZZZ"          # no such placeholder: goes out now, however long the stream takes
    assert restorer.feed("b ⟨API") == "b " and restorer.held == "⟨API"
    assert restorer.feed("_KEY_1⟩ c") == f"{KEY} c" and restorer.held == ""
    assert restorer.feed("⟨EMAIL_1") == ""
    assert restorer.flush() == "⟨EMAIL_1"               # the stream ended: nothing is lost


def test_no_vault_means_no_buffering():
    restorer = StreamRestorer(None)
    assert restorer.feed("⟨API") == "⟨API" and restorer.flush() == ""


def test_stream_restores_content_and_tool_arguments_for_any_split():
    rng = random.Random(21)
    for _ in range(60):
        client, up = make()
        text = "Rotate ⟨API_KEY_1⟩, then ⟨API_KEY_2⟩ — tell ⟨EMAIL_1⟩ 完成"
        args = json.dumps({"key": "⟨API_KEY_1⟩", "to": "⟨EMAIL_1⟩"}, ensure_ascii=False)
        calls = [{"id": "c1", "name": "rotate", "arguments": args}, {"id": "c2", "name": "notify", "arguments": args}]
        up.next = [sse_bytes(reply_chunks(text, calls, rng=rng), rng=rng)]
        r = client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC)
        assert r.status_code == 200 and r.headers["x-cm-lane"] == "contributor"
        assert KEY not in json.dumps(up.calls[0]) and MAIL not in json.dumps(up.calls[0])
        message, _ = chat_message(r.text)
        assert message["content"] == f"Rotate {KEY}, then {OTHER} — tell {MAIL} 完成"
        expected = json.dumps({"key": KEY, "to": MAIL}, ensure_ascii=False)
        assert [c["function"]["arguments"] for c in message["tool_calls"]] == [expected, expected]
        assert "⟨" not in r.text


def test_a_placeholder_cut_at_the_very_end_is_flushed_when_the_stream_ends_without_a_finish_chunk():
    client, up = make()
    chunks = reply_chunks(None, done=False) + [{"choices": [{"index": 0, "delta": {"content": "x ⟨API"}}]},
                                               {"choices": [{"index": 0, "delta": {"content": "_KEY_1"}}]}]
    up.next = [sse_bytes(chunks)]       # [DONE] with no finish_reason, and the placeholder never closes
    message, _ = chat_message(client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC).text)
    assert message["content"] == "x ⟨API_KEY_1"


def test_line_separators_inside_json_text_do_not_cut_a_chunk():
    client, up = make()
    text = "one two\u0085three four"
    up.next = [sse_bytes(reply_chunks(text), rng=random.Random(3))]
    message, _ = chat_message(client.post("/v1/chat/completions", json=ask(), headers=PUBLIC).text)
    assert message["content"] == text


# ---- provenance and origin -------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["", None, "absent"])
def test_a_streamed_tool_call_is_recognized_however_the_client_spells_its_empty_content(content):
    client, up = make()
    call = {"id": "c1", "name": "run_tests", "arguments": "{}"}
    up.next = [sse_bytes(reply_chunks(None, [call]))]
    h = {**PUBLIC, "x-cm-client": "openai"}
    msgs = ask()["messages"]
    message, _ = chat_message(client.post("/v1/chat/completions", json=ask(), headers=h).text)
    if content == "absent":
        message.pop("content")
    else:
        message["content"] = content
    msgs += [message, {"role": "tool", "tool_call_id": "c1", "content": "2 passed"}]
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": msgs}, headers=h)
    assert r.headers["x-cm-lane"] == "contributor"


def test_stream_and_non_stream_record_the_same_fingerprint():
    text = "Rotate ⟨API_KEY_1⟩ and retry."
    client, up = make(default_text=text)
    plain = client.post("/v1/chat/completions", json={**with_secret(), "stream": False}, headers=PUBLIC).json()
    client, up = make(default_text=text)
    up.next = [sse_bytes(reply_chunks(text, rng=random.Random(5)))]
    streamed, _ = chat_message(client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC).text)
    assert fingerprint(streamed) == fingerprint(plain["choices"][0]["message"])
    assert client.app.state.sessions["s"].provenance.lookup(streamed) is not None


def test_contributor_reply_is_recognized_with_the_restored_values_the_client_saw():
    # The client holds the real key, the model only ever saw the placeholder.
    client, up = make()
    up.next = [sse_bytes(reply_chunks("Rotate ⟨API_KEY_1⟩ now", rng=random.Random(9)))]
    h = {**PUBLIC, "x-cm-client": "openai"}
    first = with_secret()
    r = client.post("/v1/chat/completions", json=first, headers=h)
    message, _ = chat_message(r.text)
    assert KEY in message["content"] and r.headers["x-cm-lane"] == "contributor"

    follow = {"model": "m", "stream": True, "messages": first["messages"] + [message, {"role": "user", "content": "go on"}]}
    r = client.post("/v1/chat/completions", json=follow, headers=h)
    assert r.headers["x-cm-lane"] == "contributor"          # with x-cm-client, an unknown assistant message would block
    sent = json.dumps(up.calls[1], ensure_ascii=False)
    assert KEY not in sent and "Rotate ⟨API_KEY_1⟩ now" in sent


def test_a_changed_reply_is_foreign_again():
    client, up = make()
    h = {**PUBLIC, "x-cm-client": "openai"}
    message, _ = chat_message(client.post("/v1/chat/completions", json=ask(), headers=h).text)
    message["content"] += " (edited)"
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": ask()["messages"] + [message]}, headers=h)
    assert r.headers["x-cm-lane"] == "standard"


def test_taint_from_a_streamed_standard_reply_carries_into_the_next_turn():
    client, up = make()
    h = {**PUBLIC, "x-cm-client": "anthropic"}
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "foreign line"}]
    r = client.post("/v1/chat/completions", json={"model": "m", "stream": True, "messages": history}, headers=h)
    assert r.headers["x-cm-lane"] == "standard"
    message, _ = chat_message(r.text)
    later = [{"role": "user", "content": "q2"}, message]
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": later}, headers=h)
    assert r.headers["x-cm-lane"] == "standard"             # our reply, but derived from Claude output


def test_a_partial_reply_is_not_recorded_as_ours():
    client, up = make()
    up.next = [Script(sse_bytes(reply_chunks("half a repl", done=False), done=False), fail=httpx.ReadError("cut"))]
    h = {**PUBLIC, "x-cm-client": "openai"}
    message, _ = chat_message(client.post("/v1/chat/completions", json=ask(), headers=h).text)
    assert message["content"] == "half a repl"
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": ask()["messages"] + [message]}, headers=h)
    assert r.headers["x-cm-lane"] == "standard"


# ---- ledger ----------------------------------------------------------------------------------------

def test_usage_is_requested_from_upstream_and_written_when_the_stream_ends():
    client, up = make()
    r = client.post("/v1/chat/completions", json=ask(), headers=PUBLIC)
    assert up.calls[0]["stream"] is True and up.calls[0]["stream_options"]["include_usage"] is True
    (row,) = rows(client)
    assert (row["prompt_tokens"], row["cached_tokens"], row["completion_tokens"]) == (20_000, 15_000, 1_000)
    assert row["cost"] > 0 and row["reason"] == "all context contributable after masking"
    assert row["sent_payload"] == json.dumps(ask()["messages"], ensure_ascii=False, sort_keys=True)
    # The client did not ask for usage: no chunk with empty choices for it to trip over.
    _, chunks = chat_message(r.text)
    assert all(c.get("choices") and "usage" not in c for c in chunks)


def test_a_client_that_asks_for_usage_gets_it():
    client, _ = make()
    r = client.post("/v1/chat/completions", json=ask(stream_options={"include_usage": True}), headers=PUBLIC)
    _, chunks = chat_message(r.text)
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"] == USAGE


def test_lane_headers_come_first_and_the_cost_as_an_sse_comment():
    client, _ = make()
    r = client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-cm-lane"] == "contributor" and r.headers["x-cm-billing"] == "paid"
    assert r.headers["x-cm-masked-spans"] == "3" and "->" in r.headers["x-cm-broker-chars"]
    assert "x-cm-cost" not in r.headers                     # not known yet when the headers go out
    (row,) = rows(client)
    assert f": x-cm-cost={row['cost']:.6f} x-cm-counterfactual=" in r.text
    assert r.text.endswith("data: [DONE]\n\n")


@pytest.mark.parametrize("raises", [False, True])
def test_client_disconnect_still_leaves_a_ledger_row_and_closes_upstream(raises):
    up = Upstream()
    usage_first = [frame(c) for c in reply_chunks("first ⟨API", done=False)]
    usage_first.append(frame({"choices": [], "usage": USAGE}))
    script = Script(usage_first, hang=True)
    up.next = [script]
    app = create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), transport=httpx.MockTransport(up))
    try:
        asyncio.run(drive_asgi(app, "/v1/chat/completions", with_secret(), PUBLIC, disconnect_after=1, raise_on_send=raises))
    except* OSError:        # a server whose send raises: the error goes on up, the row must still be there
        assert raises
    assert script.closed
    (lane, prompt, reason, payload) = app.state.ledger.db.execute(
        "SELECT lane, prompt_tokens, reason, sent_payload FROM requests").fetchone()
    assert lane == "contributor" and "client disconnected" in reason
    assert prompt == (0 if raises else 20_000)              # usage seen before the disconnect is kept
    assert KEY not in payload and "⟨API_KEY_1⟩" in payload  # what left the machine is on record
    assert app.state.sessions["s"].provenance._labels == {}


def test_client_disconnect_before_any_usage_is_recorded_with_zero_usage():
    up = Upstream()
    script = Script(sse_bytes(reply_chunks("hello", done=False), done=False), hang=True)
    up.next = [script]
    app = create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), transport=httpx.MockTransport(up))
    asyncio.run(drive_asgi(app, "/v1/chat/completions", ask(), PUBLIC))
    assert script.closed
    assert app.state.ledger.db.execute("SELECT COUNT(*), SUM(prompt_tokens) FROM requests").fetchone() == (1, 0)


def test_client_disconnect_over_a_real_socket():
    up = Upstream()
    script = Script(sse_bytes(reply_chunks("hello there", done=False), done=False), hang=True)
    up.next = [script]
    app = create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), transport=httpx.MockTransport(up))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        with httpx.Client(trust_env=False) as c, c.stream("POST", f"http://127.0.0.1:{port}/v1/chat/completions",
                                                         json=ask(), headers=PUBLIC) as r:
            assert r.status_code == 200 and r.headers["x-cm-lane"] == "contributor"
            next(r.iter_raw())
        while time.time() < deadline and not (script.closed and app.state.ledger.summary()["requests"]):
            time.sleep(0.02)
        assert script.closed and app.state.ledger.summary()["requests"] == 1
    finally:
        server.should_exit = True
        thread.join(10)


# ---- errors ----------------------------------------------------------------------------------------

def test_held_answers_403_before_any_stream():
    client, up = make("credits")
    r = client.post("/v1/chat/completions", json=ask(), headers={**PUBLIC, "x-cm-project": "confidential"})
    assert r.status_code == 403 and r.headers["x-cm-lane"] == "held" and up.calls == []
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "not_contributable_on_credits"
    assert rows(client)[0]["lane"] == "held"


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_upstream_errors_before_the_stream_keep_their_status(status):
    client, up = make()
    up.next = [httpx.Response(status, json={"error": {"code": "nope", "message": "no"}})]
    r = client.post("/v1/chat/completions", json=ask(), headers=PUBLIC)
    assert r.status_code == status and r.json()["error"]["code"] == "nope"
    assert r.headers["content-type"].startswith("application/json") and r.headers["x-cm-lane"] == "contributor"
    assert f"upstream answered {status}" in rows(client)[0]["reason"]


def test_an_upstream_error_that_is_not_json_is_still_an_error():
    client, up = make()
    up.next = [httpx.Response(502, text="<html>bad gateway</html>")]
    r = client.post("/v1/chat/completions", json=ask(), headers=PUBLIC)
    assert r.status_code == 502 and "bad gateway" in r.json()["error"]["message"]


def test_an_unreachable_upstream_is_a_502_with_a_row():
    client, up = make()
    up.next = [httpx.ConnectError("refused at 10.0.0.1")]
    r = client.post("/v1/chat/completions", json=ask(), headers=PUBLIC)
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_unreachable"
    assert "10.0.0.1" not in r.text
    assert "upstream unreachable" in rows(client)[0]["reason"]


def test_upstream_failure_after_streaming_started_is_an_sse_error():
    client, up = make()
    script = Script(sse_bytes(reply_chunks("partial ⟨API_KEY_1", done=False), done=False), fail=httpx.ReadError("cut"))
    up.next = [script]
    r = client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC)
    assert r.status_code == 200 and script.closed
    events = [d for _, d in parse_sse(r.text)]
    assert events[-1] == "[DONE]"
    assert json.loads(events[-2])["error"]["code"] == "upstream_disconnected"
    message, _ = chat_message("\n\n".join(f"data: {e}" for e in events[:-2]))
    assert message["content"] == "partial ⟨API_KEY_1"       # what was held back is not lost
    (row,) = rows(client)
    assert "stream interrupted: upstream_disconnected" in row["reason"] and row["prompt_tokens"] == 0


@pytest.mark.parametrize("wire, code", [
    (b'event: error\ndata: {"code": "server_shutting_down", "message": "bye"}\n\n', "server_shutting_down"),
    (b'data: {"error": {"code": "overloaded", "message": "busy"}}\n\n', "overloaded"),
    (b"data: {not json\n\n", "upstream_bad_chunk"),
    (b"", "upstream_disconnected"),       # the connection simply ends, no finish_reason, no [DONE]
])
def test_failures_inside_the_stream(wire, code):
    client, up = make()
    up.next = [sse_bytes(reply_chunks("partial", done=False), done=False) + [wire]]
    r = client.post("/v1/chat/completions", json=ask(), headers=PUBLIC)
    assert r.status_code == 200
    assert json.loads(parse_sse(r.text)[-2][1])["error"]["code"] == code
    assert f"stream interrupted: {code}" in rows(client)[0]["reason"]


def test_an_upstream_that_ignores_stream_true_still_works():
    client, up = make()
    up.next = [httpx.Response(200, json={
        "model": "m", "usage": USAGE, "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": "Rotate ⟨API_KEY_1⟩",
            "tool_calls": [{"id": "c", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}}]})]
    r = client.post("/v1/chat/completions", json=with_secret(), headers=PUBLIC)
    message, _ = chat_message(r.text)
    assert message["content"] == f"Rotate {KEY}" and message["tool_calls"][0]["function"]["name"] == "f"
    assert rows(client)[0]["prompt_tokens"] == 20_000


# ---- lanes and billing -----------------------------------------------------------------------------

def test_local_lane_streams_and_nothing_reaches_meta():
    client, up = make("credits", local=True, default_text="kept here")
    r = client.post("/v1/chat/completions", json=ask("our unreleased plan"), headers={**PUBLIC, "x-cm-project": "confidential"})
    assert r.status_code == 200 and r.headers["x-cm-lane"] == "local"
    assert up.hosts == ["local"] and up.calls[0]["model"] == "muse-glimmer"
    assert chat_message(r.text)[0]["content"] == "kept here"
    (row,) = rows(client)
    assert row["lane"] == "local" and row["cost"] == 0 and row["sent_payload"] is None


def test_standard_lane_does_not_touch_placeholders_the_model_may_print():
    client, up = make(default_text="the literal ⟨API_KEY_1⟩")
    r = client.post("/v1/chat/completions", json=with_secret(), headers={**PUBLIC, "x-cm-project": "confidential"})
    assert r.headers["x-cm-lane"] == "standard"
    assert chat_message(r.text)[0]["content"] == "the literal ⟨API_KEY_1⟩"


def test_on_credits_every_streamed_meta_request_is_a_clean_contributor_request():
    rng = random.Random(13)
    client, up = make("credits")
    lanes = set()
    for i in range(120):
        msgs = [{"role": "user", "content": rng.choice(["fix the parser", f"token {KEY} fails"])}]
        if rng.random() < 0.5:
            msgs.append({"role": "tool", "tool_call_id": "t", "content": f"401 for token {KEY}"})
        if rng.random() < 0.3:
            msgs.append({"role": "assistant", "content": "earlier answer"})
        headers = {"x-cm-session": f"s{i}", "x-cm-project": rng.choice(["public", "own_ip", "confidential"]),
                   "x-cm-dial": rng.choice(["public", "own_ip"]), "x-cm-client": rng.choice(["anthropic", "openai", "unknown"])}
        r = client.post("/v1/chat/completions", json={"model": "m", "stream": True, "messages": msgs}, headers=headers)
        lanes.add(r.headers["x-cm-lane"])
    assert lanes == {"contributor", "held"} and up.calls
    for body in up.calls:
        assert body["model"] == "muse-spark-1.3-contributor" and KEY not in json.dumps(body)


# ---- fields next to the messages -------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True])
def test_secrets_in_tool_definitions_are_masked_on_contributor(stream):
    client, up = make()
    tools = [{"type": "function", "function": {"name": "deploy", "description": f"uses token {KEY}", "parameters": {}}}]
    body = {"model": "m", "stream": stream, "tools": tools, "user": MAIL, "messages": [{"role": "user", "content": "go"}]}
    r = client.post("/v1/chat/completions", json=body, headers=PUBLIC)
    assert r.headers["x-cm-lane"] == "contributor" and r.headers["x-cm-masked-spans"] == "2"
    sent = json.dumps(up.calls[0], ensure_ascii=False)
    assert KEY not in sent and MAIL not in sent and "⟨API_KEY_1⟩" in sent


@pytest.mark.parametrize("stream", [False, True])
def test_chat_requests_cannot_carry_stored_state_upstream(stream):
    client, up = make()
    body = {"model": "m", "stream": stream, "previous_response_id": "resp_1", "messages": [{"role": "user", "content": "go"}]}
    r = client.post("/v1/chat/completions", json=body, headers=PUBLIC)
    assert r.status_code == 400 and "previous_response_id" in r.json()["error"]["message"] and up.calls == []
    r = client.post("/v1/chat/completions", json={**body, "previous_response_id": None, "store": True}, headers=PUBLIC)
    assert r.status_code == 200 and up.calls[0]["store"] is False
