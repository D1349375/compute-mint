"""/v1/responses takes the same path as /v1/chat/completions, and refuses what could bypass it."""
import asyncio
import json
import random

import httpx
import pytest
from fastapi.testclient import TestClient
from upstream_sim import USAGE, Script, Upstream, drive_asgi, parse_sse, reply_chunks, sse_bytes

from compute_mint.app import Config, create_app
from compute_mint.labels import Label
from compute_mint.responses import BadRequest, reply_messages, to_chat

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
ROOT = "/work/shop"
CLIENTS = ('{"clients": [{"name": "Zorbel Quillmark Co.", "contact": "Hanne Voskuijlen", "tax_id": "TW90210017"}]}')
PUBLIC = {"x-cm-session": "s", "x-cm-project": "public", "x-cm-root": ROOT}
CODEX = {**PUBLIC, "x-cm-client": "openai"}


def make(billing="paid", local=False, default_text="ok"):
    up = Upstream(default_text)
    config = Config(api_base="https://mock/v1", api_key="t", billing=billing,
                    local_api_base="http://local/v1" if local else "")
    return TestClient(create_app(config, transport=httpx.MockTransport(up))), up


def post(client, body, headers=PUBLIC):
    return client.post("/v1/responses", json={"model": "any", **body}, headers=headers)


def events(text):
    return [(kind, json.loads(data)) for kind, data in parse_sse(text)]


def user(text):
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def fcall(call_id, name, **args):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(args)}


def foutput(call_id, output):
    return {"type": "function_call_output", "call_id": call_id, "output": output}


def rows(client):
    return client.app.state.ledger.db.execute("SELECT lane, reason, prompt_tokens FROM requests ORDER BY id").fetchall()


# ---- translation -----------------------------------------------------------------------------------

def test_a_string_input_and_instructions():
    converted = to_chat({"input": "hi", "instructions": "be brief"})
    assert converted.messages == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    assert converted.fields == {"store": False} and converted.unlabeled is None


def test_message_items_in_every_shape():
    messages = to_chat({"input": [
        {"role": "user", "content": "plain"},
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]},
        {"type": "message", "role": "system", "content": "sys"},
        user("a"),
        {"type": "message", "role": "assistant", "id": "msg_1", "status": "completed",
         "content": [{"type": "output_text", "text": "answer", "annotations": []}]},
    ]}).messages
    assert messages == [{"role": "user", "content": "plain"}, {"role": "system", "content": "rules"},
                        {"role": "system", "content": "sys"}, {"role": "user", "content": "a"},
                        {"role": "assistant", "content": "answer"}]


def test_function_calls_join_the_assistant_message_before_them_and_outputs_become_tool_messages():
    messages = to_chat({"input": [
        user("go"),
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Looking."}]},
        {"type": "reasoning", "id": "rs_1", "summary": []},      # must not split the assistant turn
        fcall("c1", "read_file", path="a.md"), fcall("c2", "read_file", path="b.md"),
        foutput("c1", "AAA"), foutput("c2", [{"type": "input_text", "text": "BBB"}]),
    ]}).messages
    assert messages[1] == {"role": "assistant", "content": "Looking.", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.md"}'}},
        {"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "b.md"}'}}]}
    assert messages[2:] == [{"role": "tool", "tool_call_id": "c1", "content": "AAA"},
                            {"role": "tool", "tool_call_id": "c2", "content": "BBB"}]


def test_tool_output_in_any_shape_keeps_its_text():
    for output in ({"content": "needle", "success": True}, ["needle"], [{"type": "other", "value": "needle"}], {"a": ["needle"]}):
        messages = to_chat({"input": [fcall("c", "f"), foutput("c", output)]}).messages
        assert "needle" in messages[-1]["content"] and isinstance(messages[-1]["content"], str)


def test_tool_shapes():
    converted = to_chat({"input": "x", "tool_choice": {"type": "function", "name": "flat"}, "tools": [
        {"type": "function", "name": "flat", "description": "d", "strict": False, "parameters": {"type": "object"}},
        {"type": "function", "function": {"name": "nested", "parameters": {}}},
        {"type": "custom", "name": "apply_patch", "description": "patch", "format": {"type": "grammar", "syntax": "lark", "definition": "start: x"}},
        {"type": "local_shell"}, {"type": "web_search"}, {"type": "image_generation"},
    ]})
    tools = converted.fields["tools"]
    assert [t["function"]["name"] for t in tools] == ["flat", "nested", "apply_patch", "local_shell"]
    assert tools[0] == {"type": "function", "function": {"name": "flat", "description": "d", "strict": False,
                                                         "parameters": {"type": "object"}}}
    assert "start: x" in tools[2]["function"]["description"]
    assert tools[2]["function"]["parameters"]["required"] == ["input"]
    assert converted.fields["tool_choice"] == {"type": "function", "function": {"name": "flat"}}
    assert converted.kinds == {"apply_patch": "custom", "local_shell": "local_shell"}


def test_only_known_fields_go_upstream():
    fields = to_chat({"input": "x", "max_output_tokens": 9, "temperature": 0.5, "top_p": 0.9, "parallel_tool_calls": False,
                      "reasoning": {"effort": "high", "summary": "auto"}, "store": True, "include": ["reasoning.encrypted_content"],
                      "metadata": {"a": "b"}, "user": "u", "prompt_cache_key": "k", "service_tier": "auto", "truncation": "auto",
                      "text": {"format": {"type": "json_schema", "name": "n", "schema": {}, "strict": True}, "verbosity": "low"}}).fields
    assert fields == {"store": False, "max_completion_tokens": 9, "temperature": 0.5, "top_p": 0.9, "parallel_tool_calls": False,
                      "reasoning_effort": "high",
                      "response_format": {"type": "json_schema", "json_schema": {"name": "n", "schema": {}, "strict": True}}}
    assert "reasoning_effort" not in to_chat({"input": "x", "reasoning": {"effort": "none"}}).fields


@pytest.mark.parametrize("bad", [
    {}, {"input": []}, {"input": 3}, {"input": [3]}, {"input": [{"type": "message", "role": "tool", "content": "x"}]},
    {"input": [{"type": "message", "role": "user", "content": [{"type": "input_file", "file_id": "f"}]}]},
    {"input": [{"type": "function_call", "name": "f"}]}, {"input": "x", "instructions": 3},
])
def test_requests_the_gateway_cannot_translate_are_400(bad):
    with pytest.raises(BadRequest):
        to_chat(bad)


# ---- state that lives elsewhere --------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("field, value", [("previous_response_id", "resp_1"), ("conversation", "conv_1"),
                                          ("prompt", {"id": "pmpt_1"}), ("background", True)])
def test_stored_state_is_refused_and_nothing_goes_upstream(field, value, stream):
    client, up = make()
    r = post(client, {"input": "go on", "stream": stream, field: value})
    assert r.status_code == 400 and up.calls == [] and rows(client) == []
    assert field in r.json()["error"]["message"] and r.json()["error"]["type"] == "invalid_request_error"


def test_the_refusal_says_why_and_what_to_do():
    client, _ = make()
    message = post(client, {"input": "x", "previous_response_id": "resp_1"}).json()["error"]["message"]
    assert "§6.1" in message and "complete input" in message


def test_null_previous_response_id_is_fine_and_never_forwarded():
    client, up = make()
    assert post(client, {"input": "go", "previous_response_id": None}).status_code == 200
    assert "previous_response_id" not in up.calls[0]


def test_item_references_and_orphan_outputs_are_refused():
    client, up = make()
    assert post(client, {"input": [{"type": "item_reference", "id": "msg_1"}]}).status_code == 400
    r = post(client, {"input": [user("go"), foutput("gone", "text from a call we never saw")]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_call_id"
    assert up.calls == []


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("store", [True, False, None])
def test_store_is_always_false_upstream(stream, store):
    client, up = make()
    r = post(client, {"input": "go", "stream": stream, "store": store})
    assert r.status_code == 200 and up.calls[0]["store"] is False


# ---- reasoning -------------------------------------------------------------------------------------

REASONING = {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAAAB-opaque-blob",
             "summary": [{"type": "summary_text", "text": "summary from another model"}],
             "content": [{"type": "reasoning_text", "text": "chain of thought"}]}


@pytest.mark.parametrize("stream", [False, True])
def test_reasoning_is_never_sent_and_keeps_the_request_off_contributor(stream):
    client, up = make()
    r = post(client, {"input": [user("explain quicksort"), REASONING], "stream": stream})
    assert r.status_code == 200 and r.headers["x-cm-lane"] == "standard"
    sent = json.dumps(up.calls[0])
    assert up.calls[0]["model"] == "muse-spark-1.3"
    for text in ("opaque-blob", "summary from another model", "chain of thought"):
        assert text not in sent
    assert "reasoning item" in rows(client)[0][1]


def test_reasoning_on_credits_is_held():
    client, up = make("credits")
    r = post(client, {"input": [user("explain quicksort"), REASONING]})
    assert r.status_code == 403 and r.headers["x-cm-lane"] == "held" and up.calls == []


def test_other_model_generated_items_are_treated_the_same():
    client, up = make()
    for kind in ("web_search_call", "compaction", "something_new"):
        r = post(client, {"input": [user("go"), {"type": kind, "id": "x", "encrypted_content": "BLOB", "query": "q"}]},
                 {**PUBLIC, "x-cm-session": kind})
        assert r.headers["x-cm-lane"] == "standard" and "BLOB" not in json.dumps(up.calls[-1])


def test_a_reply_generated_next_to_unlabeled_content_cannot_carry_it_into_contributor():
    client, _ = make()
    image = {"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": "what is this"}, {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]}
    r = post(client, {"input": [image]}, CODEX)
    assert r.headers["x-cm-lane"] == "standard"
    output = r.json()["output"]
    r = post(client, {"input": [user("go on"), *output]}, CODEX)
    assert r.headers["x-cm-lane"] == "standard"


# ---- tool output: the leak protection has to hold here too -----------------------------------------

def base_input():
    return [{"type": "message", "role": "developer", "content": "You are an agent."}, user("Fix the reminder wording")]


def _gateway_call(client, session, name, args):
    """The model (through the gateway) asks for a tool; returns the items the client echoes back."""
    up = client.app.state.upstream_sim
    call = {"id": "c1", "name": name, "arguments": json.dumps(args)}
    headers = {**PUBLIC, "x-cm-session": session, "x-cm-project": "own_ip", "x-cm-dial": "own_ip", "x-cm-client": "openai"}
    up.next = [sse_bytes(reply_chunks(None, [call]))]
    r = post(client, {"input": base_input(), "stream": True}, headers)
    assert r.headers["x-cm-lane"] == "contributor"
    return events(r.text)[-1][1]["response"]["output"], headers


@pytest.fixture
def agent():
    client, up = make()
    client.app.state.upstream_sim = up
    return client, up


@pytest.mark.parametrize("stream", [False, True])
def test_canary_in_function_call_output_is_masked_on_contributor(agent, stream):
    client, up = agent
    output, headers = _gateway_call(client, "m", "run_tests", {})
    r = post(client, {"stream": stream, "input": base_input() + output + [foutput("c1", f"401 for token {KEY}")]}, headers)
    assert r.headers["x-cm-lane"] == "contributor" and r.headers["x-cm-masked-spans"] == "1"
    assert KEY not in json.dumps(up.calls[-1]) and "401 for token ⟨API_KEY_1⟩" in json.dumps(up.calls[-1], ensure_ascii=False)


@pytest.mark.parametrize("output", [{"content": f"token {KEY}", "success": True}, [{"type": "input_text", "text": f"token {KEY}"}],
                                    [f"token {KEY}"], [{"type": "other", "value": f"token {KEY}"}]])
def test_canary_in_structured_function_call_output_is_masked_too(agent, output):
    client, up = agent
    items, headers = _gateway_call(client, "n", "run_tests", {})
    r = post(client, {"input": base_input() + items + [foutput("c1", output)]}, headers)
    assert r.headers["x-cm-lane"] == "contributor" and KEY not in json.dumps(up.calls[-1])


def test_a_foreign_call_with_a_canary_output_stays_off_contributor():
    client, up = make()
    r = post(client, {"input": [user("deploy fails"), fcall("c", "bash", command="ls"), foutput("c", f"401 for token {KEY}")]}, CODEX)
    assert r.headers["x-cm-lane"] == "standard" and up.calls[0]["model"] == "muse-spark-1.3"


def test_a_function_call_output_read_from_a_credential_file_stays_off_contributor(agent):
    client, up = agent
    output, headers = _gateway_call(client, "a", "read_file", {"path": f"{ROOT}/.env"})
    r = post(client, {"input": base_input() + output + [foutput("c1", "DB_HOST=db1.internal.example")]}, headers)
    assert r.headers["x-cm-lane"] == "standard" and up.calls[-1]["model"] == "muse-spark-1.3"
    assert all("db1.internal" not in json.dumps(c) for c in up.calls if c["model"].endswith("contributor"))


def test_the_arguments_reach_the_policy_so_a_reviewed_path_can_flow(agent):
    client, up = agent
    client.app.state.policy.set_rule(f"{ROOT}/docs/**", Label.PUBLIC)
    output, headers = _gateway_call(client, "b", "read_file", {"path": f"{ROOT}/docs/guide.md"})
    r = post(client, {"input": base_input() + output + [foutput("c1", "Public text.")]}, headers)
    assert r.headers["x-cm-lane"] == "contributor"
    sent = up.calls[-1]["messages"]
    assert sent[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Public text."}
    assert sent[-2]["tool_calls"][0]["id"] == "c1"
    # the same call on a file nobody reviewed goes to the review queue instead
    output, headers = _gateway_call(client, "c", "read_file", {"path": f"{ROOT}/data/x.md"})
    r = post(client, {"input": base_input() + output + [foutput("c1", "Unreviewed.")]}, headers)
    assert r.headers["x-cm-lane"] == "standard"
    assert [q["path"] for q in client.get("/v1/review").json()["pending"]] == [f"{ROOT}/data/x.md"]


@pytest.mark.parametrize("stream", [False, True])
def test_paths_printed_in_a_function_call_output_label_it(agent, stream):
    client, up = agent
    client.app.state.policy.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    client.app.state.policy.set_rule(f"{ROOT}/config/**", Label.CONFIDENTIAL)
    output, headers = _gateway_call(client, "d", "run_tests", {})
    text = f'tests/test_a.py:1: E\n  File "{ROOT}/config/secrets_loader.py", line 4, in load\n'
    r = post(client, {"stream": stream, "input": base_input() + output + [foutput("c1", text)]}, headers)
    assert r.headers["x-cm-lane"] == "standard"
    assert "output-path" in rows(client)[-1][1]


@pytest.mark.parametrize("stream", [False, True])
def test_names_read_earlier_do_not_leak_through_function_call_output(agent, stream):
    client, up = agent
    client.app.state.policy.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    output, headers = _gateway_call(client, "e", "read_file", {"path": f"{ROOT}/config/clients.json"})
    assert post(client, {"input": base_input() + output + [foutput("c1", CLIENTS)]}, headers).headers["x-cm-lane"] == "standard"

    output, headers = _gateway_call(client, "f", "run_tests", {})
    test_output = "tests/test_a.py:15: AssertionError\nE  clients = [{'contact': 'Hanne Voskuijlen'}]\n"
    r = post(client, {"stream": stream, "input": base_input() + output + [foutput("c1", test_output)]}, headers)
    assert r.headers["x-cm-lane"] == "standard" and "fingerprint" in rows(client)[-1][1]
    contributor = [json.dumps(c) for c in up.calls if c["model"].endswith("contributor")]
    assert contributor and not any("Voskuijlen" in c or "Quillmark" in c for c in contributor)


# ---- origin ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True])
def test_codex_history_written_by_gpt_never_goes_to_contributor(stream):
    client, up = make()
    history = [user("explain quicksort"),
               {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "From GPT."}]},
               user("and mergesort?")]
    r = post(client, {"input": history, "stream": stream}, CODEX)
    assert r.headers["x-cm-lane"] == "standard" and "by origin" in rows(client)[0][1]
    # a function_call counts too, and without x-cm-client the origin is unknown, which blocks as well
    r = post(client, {"input": [user("go"), fcall("c", "bash", command="ls"), foutput("c", "x")], "stream": stream},
             {**PUBLIC, "x-cm-session": "2"})
    assert r.headers["x-cm-lane"] == "standard"


def test_codex_history_on_credits_is_held():
    client, up = make("credits")
    history = [user("explain"), {"type": "message", "role": "assistant", "content": "From GPT."}]
    r = post(client, {"input": history}, CODEX)
    assert r.status_code == 403 and up.calls == []


def test_a_bad_client_header_is_rejected():
    client, up = make()
    r = post(client, {"input": "x"}, {"x-cm-client": "meta"})
    assert r.status_code == 400 and up.calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_our_own_reply_comes_back_as_meta_with_the_restored_values(stream):
    client, up = make()
    calls = [{"id": "c1", "name": "rotate", "arguments": '{"key": "⟨API_KEY_1⟩"}'}]
    text = "Rotating ⟨API_KEY_1⟩."
    if stream:
        up.next = [sse_bytes(reply_chunks(text, calls, rng=random.Random(4)), rng=random.Random(4))]
    else:
        up.next = [httpx.Response(200, json={"usage": USAGE, "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": text,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "rotate", "arguments": calls[0]["arguments"]}}]}}]})]
    first = [user(f"401 for token {KEY}")]
    r = post(client, {"input": first, "stream": stream}, CODEX)
    assert r.headers["x-cm-lane"] == "contributor"
    output = events(r.text)[-1][1]["response"]["output"] if stream else r.json()["output"]
    assert [i["type"] for i in output] == ["message", "function_call"]
    assert output[0]["content"][0]["text"] == f"Rotating {KEY}."
    assert json.loads(output[1]["arguments"]) == {"key": KEY} and output[1]["call_id"] == "c1"

    r = post(client, {"input": first + output + [foutput("c1", "rotated")], "stream": stream}, CODEX)
    assert r.headers["x-cm-lane"] == "contributor"          # recognized; a foreign assistant message would block
    sent = json.dumps(up.calls[1], ensure_ascii=False)
    assert KEY not in sent and "⟨API_KEY_1⟩" in sent


@pytest.mark.parametrize("order", ["together", "interleaved", "reversed_outputs"])
def test_parallel_calls_are_recognized_however_the_client_replays_them(order):
    client, up = make()
    calls = [{"id": "c1", "name": "a", "arguments": "{}"}, {"id": "c2", "name": "b", "arguments": "{}"}]
    up.next = [sse_bytes(reply_chunks("Both.", calls))]
    r = post(client, {"input": [user("go")], "stream": True}, CODEX)
    text, one, two = events(r.text)[-1][1]["response"]["output"]
    outputs = [foutput("c1", "1"), foutput("c2", "2")]
    replay = {"together": [text, one, two, *outputs], "interleaved": [text, one, outputs[0], two, outputs[1]],
              "reversed_outputs": [text, one, two, outputs[1], outputs[0]]}[order]
    r = post(client, {"input": [user("go"), *replay]}, CODEX)
    assert r.headers["x-cm-lane"] == "contributor"


def test_an_edited_echo_is_foreign():
    client, up = make()
    r = post(client, {"input": [user("go")]}, CODEX)
    item = r.json()["output"][0]
    item["content"][0]["text"] += " (edited)"
    assert post(client, {"input": [user("go"), item]}, CODEX).headers["x-cm-lane"] == "standard"


def test_custom_and_local_shell_tools_round_trip():
    client, up = make()
    patch = "*** Begin Patch\n*** Update File: a.py\n⟨API_KEY_1⟩\n*** End Patch\n"
    calls = [{"id": "c1", "name": "apply_patch", "arguments": json.dumps({"input": patch}, ensure_ascii=False)},
             {"id": "c2", "name": "local_shell", "arguments": json.dumps({"command": ["ls"], "workdir": ROOT})}]
    up.next = [sse_bytes(reply_chunks(None, calls))]
    tools = [{"type": "custom", "name": "apply_patch", "description": "patch"}, {"type": "local_shell"}]
    first = [user(f"key {KEY}")]
    r = post(client, {"input": first, "tools": tools, "stream": True}, CODEX)
    stream = events(r.text)
    output = stream[-1][1]["response"]["output"]
    assert output[0]["type"] == "custom_tool_call" and output[0]["input"] == patch.replace("⟨API_KEY_1⟩", KEY)
    assert output[1]["type"] == "local_shell_call" and output[1]["action"] == {
        "type": "exec", "command": ["ls"], "env": {}, "working_directory": ROOT}
    kinds = [k for k, _ in stream]
    assert "response.custom_tool_call_input.done" in kinds and "response.function_call_arguments.delta" not in kinds

    replay = first + output + [{"type": "custom_tool_call_output", "call_id": "c1", "output": "Success."},
                               foutput("c2", "nothing here")]
    r = post(client, {"input": replay, "tools": tools}, CODEX)
    assert r.headers["x-cm-lane"] == "contributor"
    sent = up.calls[1]["messages"]
    assert sent[1]["tool_calls"][0]["function"]["name"] == "apply_patch" and KEY not in json.dumps(sent)
    assert json.loads(sent[1]["tool_calls"][1]["function"]["arguments"])["command"] == ["ls"]


def test_reply_messages_cover_every_contiguous_run():
    items = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "t"}]},
             {"type": "function_call", "call_id": "a", "name": "a", "arguments": "{}"},
             {"type": "function_call", "call_id": "b", "name": "b", "arguments": "{}"}]
    shapes = [(m.get("content"), tuple(c["id"] for c in m.get("tool_calls", []))) for m in reply_messages(items)]
    assert sorted(shapes, key=str) == sorted([("t", ()), ("t", ("a",)), ("t", ("a", "b")), (None, ("a",)), (None, ("a", "b")),
                                              (None, ("b",))], key=str)


# ---- non-streaming output --------------------------------------------------------------------------

def test_non_streaming_response_shape_and_ledger():
    client, up = make(default_text="Done.")
    r = post(client, {"input": "explain quicksort", "instructions": "be brief", "metadata": {"a": "b"}})
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "response" and body["status"] == "completed" and body["store"] is False
    assert body["id"].startswith("resp_") and body["previous_response_id"] is None
    assert body["output"][0]["type"] == "message" and body["output"][0]["content"][0]["text"] == "Done."
    assert body["usage"] == {"input_tokens": 20_000, "input_tokens_details": {"cached_tokens": 15_000}, "output_tokens": 1_000,
                             "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 21_000}
    assert r.headers["x-cm-lane"] == "contributor" and float(r.headers["x-cm-cost"]) > 0
    assert up.calls[0]["messages"][0] == {"role": "system", "content": "be brief"}
    assert client.get("/v1/ledger/summary").json()["requests"] == 1


@pytest.mark.parametrize("finish, reason", [("length", "max_output_tokens"), ("content_filter", "content_filter")])
def test_an_interrupted_generation_is_incomplete(finish, reason):
    client, up = make()
    up.next = [sse_bytes(reply_chunks("cut off", finish=finish))]
    last_kind, last = events(post(client, {"input": "x", "stream": True}).text)[-1]
    assert last_kind == "response.incomplete" and last["response"]["incomplete_details"] == {"reason": reason}


def test_upstream_errors_pass_through_on_the_non_streaming_path():
    client, up = make()
    up.next = [httpx.Response(429, json={"error": {"code": "rate_limited", "message": "slow"}})]
    r = post(client, {"input": "x"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


# ---- streaming events ------------------------------------------------------------------------------

def test_text_stream_events_in_order():
    client, up = make()
    up.next = [sse_bytes(reply_chunks("Rotate ⟨API_KEY_1⟩ now", rng=random.Random(8)), rng=random.Random(8))]
    r = post(client, {"input": [user(f"token {KEY}")], "stream": True}, PUBLIC)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-cm-lane"] == "contributor" and r.headers["x-cm-masked-spans"] == "1"
    stream = events(r.text)
    kinds = [k for k, _ in stream]
    assert kinds[:4] == ["response.created", "response.in_progress", "response.output_item.added", "response.content_part.added"]
    assert kinds[-4:] == ["response.output_text.done", "response.content_part.done", "response.output_item.done", "response.completed"]
    assert all(k == d["type"] for k, d in stream)
    assert [d["sequence_number"] for _, d in stream] == list(range(len(stream)))
    assert "".join(d["delta"] for k, d in stream if k == "response.output_text.delta") == f"Rotate {KEY} now"
    assert next(d["text"] for k, d in stream if k == "response.output_text.done") == f"Rotate {KEY} now"
    done = stream[-1][1]["response"]
    assert done["status"] == "completed" and done["usage"]["input_tokens"] == 20_000
    assert done["output"][0]["content"][0]["text"] == f"Rotate {KEY} now"
    assert stream[0][1]["response"]["status"] == "in_progress" and stream[0][1]["response"]["output"] == []
    assert "⟨" not in r.text
    assert ": x-cm-cost=" in r.text and "x-cm-cost" not in r.headers


def test_function_call_stream_events():
    client, up = make()
    args = json.dumps({"key": "⟨API_KEY_1⟩", "path": "a.py"}, ensure_ascii=False)
    up.next = [sse_bytes(reply_chunks(None, [{"id": "c1", "name": "edit", "arguments": args}], rng=random.Random(2)))]
    stream = events(post(client, {"input": [user(f"token {KEY}")], "stream": True}, PUBLIC).text)
    added = next(d for k, d in stream if k == "response.output_item.added")
    assert added["item"]["type"] == "function_call" and added["item"]["call_id"] == "c1" and added["item"]["name"] == "edit"
    deltas = [d for k, d in stream if k == "response.function_call_arguments.delta"]
    assert deltas and all(d["item_id"] == added["item"]["id"] and d["output_index"] == 0 for d in deltas)
    expected = json.dumps({"key": KEY, "path": "a.py"})
    assert "".join(d["delta"] for d in deltas) == expected
    done = next(d for k, d in stream if k == "response.function_call_arguments.done")
    assert done["arguments"] == expected and done["name"] == "edit"
    item = next(d for k, d in stream if k == "response.output_item.done")["item"]
    assert item["arguments"] == expected and item["status"] == "completed"
    assert stream[-1][1]["response"]["output"] == [item]


def test_upstream_failure_after_start_is_response_failed():
    client, up = make()
    script = Script(sse_bytes(reply_chunks("partial", done=False), done=False), fail=httpx.ReadError("cut"))
    up.next = [script]
    r = post(client, {"input": "x", "stream": True}, PUBLIC)
    kind, data = events(r.text)[-1]
    assert kind == "response.failed" and data["response"]["status"] == "failed"
    assert data["response"]["error"]["code"] == "upstream_disconnected"
    assert script.closed and "stream interrupted" in rows(client)[0][1]


def test_held_and_upstream_errors_come_before_the_stream():
    client, up = make("credits")
    r = post(client, {"input": "plan", "stream": True}, {**PUBLIC, "x-cm-project": "confidential"})
    assert r.status_code == 403 and r.headers["x-cm-lane"] == "held" and up.calls == []
    assert r.headers["content-type"].startswith("application/json")

    client, up = make()
    up.next = [httpx.Response(503, json={"error": {"code": "busy", "message": "m"}})]
    r = post(client, {"input": "x", "stream": True}, PUBLIC)
    assert r.status_code == 503 and r.json()["error"]["code"] == "busy"


def test_local_lane_on_the_responses_path():
    client, up = make("credits", local=True, default_text="kept here")
    r = post(client, {"input": "our plan", "stream": True}, {**PUBLIC, "x-cm-project": "confidential"})
    assert r.headers["x-cm-lane"] == "local" and up.hosts == ["local"]
    assert events(r.text)[-1][1]["response"]["output"][0]["content"][0]["text"] == "kept here"
    assert rows(client)[0][0] == "local"


def test_client_disconnect_on_the_responses_path_is_recorded():
    up = Upstream()
    script = Script(sse_bytes(reply_chunks("hello", done=False), done=False), hang=True)
    up.next = [script]
    app = create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), transport=httpx.MockTransport(up))
    asyncio.run(drive_asgi(app, "/v1/responses", {"input": "x", "stream": True}, PUBLIC, disconnect_after=3))
    assert script.closed
    assert "client disconnected" in app.state.ledger.db.execute("SELECT reason FROM requests").fetchone()[0]


# ---- credits ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True])
def test_on_credits_tool_output_carried_through_this_path_never_reaches_meta_unclean(stream):
    # The calls are the gateway's own, so these requests really can go to Contributor: only labels stop them.
    rng = random.Random(23)
    client, up = make("credits")
    client.app.state.upstream_sim = up
    client.app.state.policy.set_rule(f"{ROOT}/docs/**", Label.PUBLIC)
    lanes = []
    for i in range(80):
        name, args, text = rng.choice([
            ("read_file", {"path": f"{ROOT}/.env"}, "DB_HOST=db1.internal.example"),
            ("read_file", {"path": f"{ROOT}/config/clients.json"}, CLIENTS),
            ("read_file", {"path": f"{ROOT}/docs/a.md"}, "Public text."),
            ("run_tests", {}, f"401 for token {KEY}"),
            ("run_tests", {}, "2 passed"),
        ])
        output, headers = _gateway_call(client, f"s{i}", name, args)
        r = post(client, {"stream": stream, "input": base_input() + output + [foutput("c1", text)]}, headers)
        lanes.append(r.headers["x-cm-lane"])
    assert set(lanes) == {"contributor", "held"}
    for body in up.calls:
        sent = json.dumps(body)
        assert body["model"] == "muse-spark-1.3-contributor" and KEY not in sent
        assert "db1.internal" not in sent and "Quillmark" not in sent and "Voskuijlen" not in sent


@pytest.mark.parametrize("stream", [False, True])
def test_on_credits_every_meta_request_from_this_path_is_a_clean_contributor_request(stream):
    rng = random.Random(17)
    client, up = make("credits")
    lanes = set()
    for i in range(150):
        items: list = [user(rng.choice(["fix the parser", f"token {KEY} fails"]))]
        if rng.random() < 0.4:
            items += [fcall("c", "read_file", path=rng.choice([f"{ROOT}/.env", f"{ROOT}/docs/a.md"])),
                      foutput("c", f"401 for token {KEY}")]
        if rng.random() < 0.2:
            items.append({"type": "message", "role": "assistant", "content": "earlier answer"})
        if rng.random() < 0.2:
            items.append(REASONING)
        headers = {"x-cm-session": f"s{i}", "x-cm-project": rng.choice(["public", "own_ip", "confidential"]),
                   "x-cm-dial": rng.choice(["public", "own_ip"]), "x-cm-client": rng.choice(["anthropic", "openai", "unknown"])}
        r = post(client, {"input": items, "stream": stream, "previous_response_id": None}, headers)
        lanes.add(r.headers["x-cm-lane"])
    assert lanes == {"contributor", "held"} and up.calls
    for body in up.calls:
        text = json.dumps(body)
        assert body["model"] == "muse-spark-1.3-contributor"
        assert KEY not in text and "opaque-blob" not in text and "previous_response_id" not in text and body["store"] is False
