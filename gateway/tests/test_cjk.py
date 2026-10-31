"""Chinese, Japanese and Korean text: no spaces and no capitals must not open a way past the protections."""
import json
import random
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from upstream_sim import Upstream, parse_sse, reply_chunks, sse_bytes

from compute_mint.app import Config, create_app
from compute_mint.detect import find_spans, has_floor
from compute_mint.fingerprint import SCORE, FingerprintIndex, extract
from compute_mint.labels import Label
from compute_mint.ledger import Ledger
from compute_mint.outpaths import paths_in_text
from compute_mint.policy import Policy
from compute_mint.vault import Vault

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
ROOT = "/w"
MAIL = "ines.varga" + "@quill-" + "example.io"
PERSON_ID = "A1" + "23456789"
PHONE = "0912" + "345678"
CARD = "4111-" + "1111-" + "1111-" + "1111"
CLIENTS_CSV = "客戶名稱,聯絡人,狀態\n台灣鳳梨股份有限公司,王小明,已付款\n大河電子有限公司,陳大文,處理中\n"
PUBLIC = {"x-cm-session": "s", "x-cm-project": "public"}


# ---- detectors -------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [KEY, AWS, PERSON_ID, MAIL, PHONE, CARD])
@pytest.mark.parametrize("before, after", [("金鑰", ""), ("", "是機密"), ("金鑰", "是機密"), ("（", "）"), ("「", "」"), ("值：", "。"),
                                           ("値は", "です"), ("값은", "입니다"), ("、", "，")])
def test_a_secret_next_to_cjk_text_or_punctuation_is_found_whole(value, before, after):
    spans = find_spans(before + value + after)
    assert [s.text for s in spans] == [value]


def test_an_email_is_masked_as_a_whole():
    text = f"信箱{MAIL}的主人"
    masked, n = Vault().mask(text)
    assert n == 1 and masked == "信箱⟨EMAIL_1⟩的主人"
    assert "ines" not in masked and "varga" not in masked


@pytest.mark.parametrize("text, value", [
    ("ines.varga＠quill-example.io", "ines.varga＠quill-example.io"),
    ("信箱ines.varga＠quill．example．io的", "ines.varga＠quill．example．io"),
    ("電話０９１２３４５６７８。", "０９１２３４５６７８"),
    ("證號Ａ１２３４５６７８９", "Ａ１２３４５６７８９"),
    ("ｓｋ－a1B2c3D4e5F6g7H8i9J0k1L2。", "ｓｋ－a1B2c3D4e5F6g7H8i9J0k1L2"),
])
def test_full_width_forms_count_and_restore_as_written(text, value):
    vault = Vault()
    masked, n = vault.mask(text)
    assert n == 1 and value not in masked and vault.rehydrate(masked) == text


@pytest.mark.parametrize("text", ["password：Abcdefgh12345", "密碼：Abcdefgh12345", "密码=Abcdefgh12345", "金鑰: Abcdefgh12345", "令牌＝Abcdefgh12345"])
def test_secret_assignments_in_cjk(text):
    assert [s.text for s in find_spans(text)] == ["Abcdefgh12345"]


def test_ascii_boundaries_still_refuse_substrings():
    for text in ["task-a1B2c3D4e5F6g7H8i9J0k1L2", "XA123456789", "A1234567890", "xAKIAABCDEFGHIJKLMNOP"]:
        assert not has_floor(text), text


@pytest.mark.parametrize("endpoint", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("stream", [False, True])
def test_on_credits_secrets_glued_to_chinese_never_reach_meta(endpoint, stream):
    rng = random.Random(29)
    up = Upstream()
    client = TestClient(create_app(Config(api_base="https://mock/v1", api_key="t", billing="credits"), transport=httpx.MockTransport(up)))
    values = [KEY, AWS, PERSON_ID, MAIL, PHONE, CARD]
    for i in range(100):
        value = rng.choice(values)
        text = rng.choice(["金鑰{}", "{}是身分證", "信箱{}的", "（{}）", "値は{}です", "請看{}。"]).format(value)
        body = {"model": "m", "stream": stream, "tools": [{"type": "function", "function": {"name": "f", "description": rng.choice(["無", text])}}]}
        body.update({"messages": [{"role": "user", "content": text}]} if endpoint.endswith("completions") else {"input": text})
        if endpoint.endswith("responses"):
            body["tools"] = [{"type": "function", "name": "f", "description": body["tools"][0]["function"]["description"]}]
        r = client.post(endpoint, json=body, headers={**PUBLIC, "x-cm-session": f"s{i}"})
        assert r.headers["x-cm-lane"] == "contributor"
    assert len(up.calls) == 100
    for sent in up.calls:
        wire = json.dumps(sent, ensure_ascii=False)
        assert not any(v in wire for v in values) and "ines" not in wire and "⟨" in wire


# ---- paths -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("錯誤在config/clients.json:3行", ["config/clients.json"]),
    ("錯誤在config／clients.json：3行", ["config/clients.json"]),
    ("路徑:config/a.py", ["config/a.py"]),
    ("（config/a.py）失敗", ["config/a.py"]),
    ("「tests/test_a.py」失敗。", ["tests/test_a.py"]),
    ("檔案tests/test_a.py、config/b.yml都有錯", ["tests/test_a.py", "config/b.yml"]),
    ("在/work/shop/a.py第3行", ["/work/shop/a.py"]),
    ("位於./a.py", ["a.py"]),
    ("錯誤在a.py:12行", ["a.py"]),
    ("C:\\Users\\王小明\\a.py第3行", ["C:/Users/王小明/a.py"]),
    ("資料/客戶.csv:3", ["資料/客戶.csv"]),
    ("/w/資料/客戶.csv", ["/w/資料/客戶.csv"]),
])
def test_paths_glued_to_cjk_text(text, expected):
    assert [r.path for r in paths_in_text(text)] == expected


@pytest.mark.parametrize("text", ["版本1.5/2.0的", "和/或", "輸入/輸出", "連結https://x.example/y.py的", "信箱a@b.example的", "這是一個測試", "在a.py的"])
def test_cjk_prose_is_not_a_path(text):
    assert paths_in_text(text) == []


def test_a_path_glued_to_chinese_labels_the_output():
    p = Policy()
    p.set_rule(f"{ROOT}/config/**", Label.CONFIDENTIAL)
    msgs = [{"role": "system", "content": f"The repository root is {ROOT}."}, {"role": "user", "content": "跑測試"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "function": {"name": "run_tests", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "錯誤在config/clients.json:3行"}]
    assert p.baseline_for(msgs, Label.PUBLIC)(3) == Label.CONFIDENTIAL


# ---- fingerprints ----------------------------------------------------------------------------------

def test_terms_of_a_table():
    terms = extract(CLIENTS_CSV)
    for name in ("台灣鳳梨股份有限公司", "鳳梨股份有限公司", "台灣鳳梨", "王小明", "陳大文", "大河電子有限公司"):
        assert name in terms, name
    for ordinary in ("客戶名稱", "聯絡人", "狀態", "已付款", "處理中", "有限公司", "股份有限公司", "電子有限公司"):
        assert ordinary not in terms, ordinary


def test_terms_of_prose_are_names_only():
    terms = extract("本合約由台灣鳳梨股份有限公司與乙方簽署，方法是，高品質。甲方承辦人為王小明先生，聯絡人：陳大文。逾期依未付金額計息。", prose=True)
    assert "台灣鳳梨股份有限公司" in terms and "王小明" in terms and "陳大文" in terms
    assert not any(w in terms for w in ("方法是", "高品質", "逾期依未付金額計息"))


def test_a_clause_in_prose_is_not_a_field_but_a_csv_cell_is():
    assert "林美華" not in extract("這件事，林美華，已完成", prose=True)
    assert "林美華" in extract("聯絡人,林美華,已完成")


@pytest.mark.parametrize("field", ["高雄市", "高品質", "連線到", "程式碼", "方法論", "上市公司", "物流公司", "정보를", "서비스"])
def test_ordinary_fields_are_not_names(field):
    assert field not in extract(f"x,{field},y")


@pytest.mark.parametrize("source, name, kept", [
    ("株式会社サクラ精機,佐藤花子\n", "サクラ精機", "請求先は株式会社サクラ精機です"),
    ("株式会社サクラ精機,佐藤花子\n", "佐藤花子", "担当者 佐藤花子 に連絡"),
    ("한빛소프트 주식회사,김철수\n", "한빛소프트주식회사", "한빛소프트 주식회사 청구서 실패"),
    ("한빛소프트 주식회사,김철수\n", "김철수", "담당자 김철수 확인"),
    ("华夏明珠有限责任公司,赵敏华\n", "赵敏华", "负责人赵敏华已离职"),
])
def test_japanese_korean_and_simplified(source, name, kept):
    assert name in extract(source)
    idx = FingerprintIndex()
    idx.add("/w/x.csv", source)
    assert sum(SCORE[m.kind] for m in idx.matches(kept)) >= 2


def test_latin_terms_and_numbers_glued_to_chinese_are_still_terms():
    source = '{"contact": "Hanne Voskuijlen", "tax_id": "TW90210017", "rate": "0.0731"}'
    idx = FingerprintIndex()
    idx.add("/w/c.json", source)
    for text in ["客戶Hanne Voskuijlen的資料", "統編TW90210017是錯的", "費率0.0731不對", "統編ＴＷ９０２１００１７是錯的"]:
        assert sum(SCORE[m.kind] for m in idx.matches(text)) >= 2, text
    idx = FingerprintIndex()
    idx.add("/w/c.txt", "統編TW90210017，費率0.0731", prose=False)
    assert idx.matches("TW90210017") and idx.matches("rate 0.0731")


def test_the_index_keeps_no_plain_cjk_terms():
    idx = FingerprintIndex()
    idx.add("/w/data/clients.csv", CLIENTS_CSV)
    blob = repr(idx) + repr(vars(idx))
    assert len(idx) > 3 and "王小明" not in blob and "鳳梨" not in blob


class Agent:
    def __init__(self, billing="paid"):
        self.up = Upstream()
        self.client = TestClient(create_app(Config(api_base="https://mock/v1", api_key="t", billing=billing), transport=httpx.MockTransport(self.up)))

    def lane(self, session, name, args, output, prompt="Fix the invoice"):
        """prompt -> the model calls a tool through the gateway -> its output comes back."""
        headers = {"x-cm-session": session, "x-cm-project": "own_ip", "x-cm-dial": "own_ip", "x-cm-root": ROOT, "x-cm-client": "openai"}
        msgs = [{"role": "user", "content": prompt}]
        self.up.next = [httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]})]
        first = self.client.post("/v1/chat/completions", json={"model": "m", "messages": msgs}, headers=headers)
        assert first.headers["x-cm-lane"] == "contributor"
        msgs += [first.json()["choices"][0]["message"], {"role": "tool", "tool_call_id": "c1", "content": output}]
        r = self.client.post("/v1/chat/completions", json={"model": "m", "messages": msgs}, headers=headers)
        return r.headers["x-cm-lane"]


def test_end_to_end_chinese_names_read_earlier_stay_off_contributor():
    agent = Agent()
    assert agent.lane("a", "read_file", {"path": f"{ROOT}/data/clients.csv"}, CLIENTS_CSV) == "standard"
    assert agent.lane("b", "run_tests", {}, "FAILED test_invoice: 客戶 台灣鳳梨股份有限公司 與 王小明") == "standard"
    assert agent.lane("c", "run_tests", {}, "FAILED test_invoice: 請聯絡王小明確認金額") == "standard"
    assert agent.lane("d", "run_tests", {}, "發票寄給台灣鳳梨股份有限公司失敗了") == "standard"
    # the same test failing without those names flows
    assert agent.lane("e", "run_tests", {}, "FAILED test_invoice: 客戶名稱不可為空白") == "contributor"
    contributor = [json.dumps(c, ensure_ascii=False) for c in agent.up.calls if c["model"].endswith("contributor")]
    assert contributor and not any("鳳梨" in c or "王小明" in c for c in contributor)


def test_end_to_end_chinese_names_on_credits_are_held():
    agent = Agent("credits")
    assert agent.lane("a", "read_file", {"path": f"{ROOT}/data/clients.csv"}, CLIENTS_CSV) == "held"
    assert agent.lane("b", "run_tests", {}, "FAILED test_invoice: 客戶 台灣鳳梨股份有限公司 與 王小明") == "held"
    assert not any("鳳梨" in json.dumps(c, ensure_ascii=False) for c in agent.up.calls)


def test_a_name_the_user_typed_is_exempt_and_a_cleared_file_stops_counting():
    agent = Agent()
    agent.lane("a", "read_file", {"path": f"{ROOT}/data/clients.csv"}, CLIENTS_CSV)
    output = "FAILED test_invoice: 客戶 王小明"
    assert agent.lane("b", "run_tests", {}, output) == "standard"
    assert agent.lane("c", "run_tests", {}, output, prompt="王小明的發票壞了") == "contributor"
    agent.client.app.state.policy.set_rule(f"{ROOT}/data/**", Label.OWN_IP)
    assert agent.lane("d", "run_tests", {}, output) == "contributor"


# ---- restored tool arguments stay JSON -------------------------------------------------------------

PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nBKcwggSjAgEAAoIBAQC7\n-----END PRIVATE KEY-----"
ARGS = json.dumps({"input": "⟨PRIVATE_KEY_1⟩", "note": "a"}, ensure_ascii=False)


def _make():
    up = Upstream()
    return TestClient(create_app(Config(api_base="https://mock/v1", api_key="t", billing="paid"), transport=httpx.MockTransport(up))), up


def _plain_reply(args):
    return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": args}}]}}]})


def test_vault_keeps_arguments_json_for_every_kind_of_value():
    vault = Vault()
    masked, _ = vault.mask(f"{PEM}\n{KEY}")
    args = json.dumps({"a": "⟨PRIVATE_KEY_1⟩", "b": "⟨API_KEY_1⟩ and ⟨UNKNOWN_1⟩"}, ensure_ascii=False)
    assert json.loads(vault.rehydrate_json(args)) == {"a": PEM, "b": f"{KEY} and ⟨UNKNOWN_1⟩"}
    assert vault.rehydrate("⟨PRIVATE_KEY_1⟩") == PEM      # text that is not JSON keeps the plain value


def test_a_value_masked_out_of_json_is_not_escaped_twice():
    vault = Vault()
    args = json.dumps({"key": PEM})
    masked, n = vault.mask(args)
    assert n == 1 and "BEGIN" not in masked and json.loads(masked) == {"key": "⟨PRIVATE_KEY_1⟩"}
    assert vault.rehydrate_json(masked) == args and json.loads(vault.rehydrate_json(masked))["key"] == PEM


@pytest.mark.parametrize("value, expected", [('a"b', 'a\\"b'), ("a\\qb", "a\\\\qb"), ("a\tb", "a\\tb"), ("plain", "plain"), ("a\\nb", "a\\nb"), ('a\\"b', 'a\\"b')])
def test_json_safe_values(value, expected):
    vault = Vault()
    vault._by_placeholder["⟨X_1⟩"] = value
    assert vault.rehydrate_json('"⟨X_1⟩"') == f'"{expected}"'
    json.loads(vault.rehydrate_json('"⟨X_1⟩"'))


def test_chat_non_streaming_arguments_stay_json():
    client, up = _make()
    up.next = [_plain_reply(ARGS)]
    r = client.post("/v1/chat/completions", headers=PUBLIC, json={"model": "m", "messages": [{"role": "user", "content": f"key:\n{PEM}"}]})
    assert r.headers["x-cm-lane"] == "contributor" and "BEGIN" not in json.dumps(up.calls[0])
    assert json.loads(r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["input"] == PEM


def test_chat_streaming_arguments_stay_json_for_any_split():
    rng = random.Random(31)
    for _ in range(40):
        client, up = _make()
        up.next = [sse_bytes(reply_chunks(None, [{"id": "c1", "name": "f", "arguments": ARGS}], rng=rng), rng=rng)]
        body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": f"key:\n{PEM}"}]}
        r = client.post("/v1/chat/completions", headers=PUBLIC, json=body)
        args = ""
        for _, data in parse_sse(r.text):
            if data != "[DONE]":
                for choice in json.loads(data).get("choices") or []:
                    for part in choice["delta"].get("tool_calls") or []:
                        args += part.get("function", {}).get("arguments") or ""
        assert json.loads(args) == {"input": PEM, "note": "a"}


@pytest.mark.parametrize("stream", [False, True])
def test_responses_arguments_stay_json_and_the_next_turn_is_ours(stream):
    client, up = _make()
    up.next = [sse_bytes(reply_chunks(None, [{"id": "c1", "name": "f", "arguments": ARGS}])) if stream else _plain_reply(ARGS)]
    first = [{"role": "user", "content": f"key:\n{PEM}"}]
    h = {**PUBLIC, "x-cm-client": "openai"}
    r = client.post("/v1/responses", headers=h, json={"model": "m", "input": first, "stream": stream})
    output = json.loads(parse_sse(r.text)[-1][1])["response"]["output"] if stream else r.json()["output"]
    assert json.loads(output[0]["arguments"])["input"] == PEM
    # The client sends it back: recognized as ours, and the key is masked again in its JSON form.
    replay = first + output + [{"type": "function_call_output", "call_id": "c1", "output": "ok"}]
    args2 = json.dumps({"input": "⟨PRIVATE_KEY_2⟩"}, ensure_ascii=False)
    up.next = [_plain_reply(args2)]
    r = client.post("/v1/responses", headers=h, json={"model": "m", "input": replay})
    assert r.headers["x-cm-lane"] == "contributor" and "MIIE" not in json.dumps(up.calls[-1])
    assert json.loads(r.json()["output"][0]["arguments"])["input"] == PEM      # not escaped twice


def test_custom_tool_input_comes_back_whole():
    client, up = _make()
    args = json.dumps({"input": "*** Begin Patch\n⟨PRIVATE_KEY_1⟩\n*** End Patch"}, ensure_ascii=False)
    up.next = [_plain_reply(args)]
    r = client.post("/v1/responses", headers=PUBLIC, json={"model": "m", "input": f"key:\n{PEM}", "tools": [{"type": "custom", "name": "f"}]})
    assert r.json()["output"][0]["input"] == f"*** Begin Patch\n{PEM}\n*** End Patch"


# ---- the ledger records everything that left --------------------------------------------------------

TOOLS = [{"type": "function", "function": {"name": "deploy", "description": f"uses token {KEY}", "parameters": {}}}]


def _rows(client):
    return client.get("/v1/ledger/requests?payload=true").json()["requests"]


@pytest.mark.parametrize("stream", [False, True])
def test_sent_fields_hold_the_masked_rest_of_the_body(stream):
    client, up = _make()
    body = {"model": "m", "stream": stream, "tools": TOOLS, "user": "u1", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=PUBLIC, json=body)
    (row,) = _rows(client)
    fields = json.loads(row["sent_fields"])
    sent = {k: v for k, v in up.calls[0].items() if k not in ("model", "messages")}
    assert fields == sent                             # exactly what crossed the boundary
    assert "⟨API_KEY_1⟩" in row["sent_fields"] and KEY not in row["sent_fields"]
    assert json.loads(row["sent_payload"]) == [{"role": "user", "content": "go"}]      # still the message list


def test_sent_fields_on_the_responses_path():
    client, up = _make()
    client.post("/v1/responses", headers=PUBLIC, json={"model": "m", "input": "go", "stream": True, "tools": [
        {"type": "function", "name": "deploy", "description": f"uses token {KEY}"}]})
    fields = json.loads(_rows(client)[0]["sent_fields"])
    assert fields["store"] is False and fields["stream_options"] == {"include_usage": True}
    assert fields["tools"][0]["function"]["description"] == "uses token ⟨API_KEY_1⟩"


def test_sent_fields_are_kept_when_the_request_fails_or_the_stream_breaks():
    client, up = _make()
    up.next = [httpx.Response(500, json={"error": {"message": "x"}})]
    client.post("/v1/chat/completions", headers=PUBLIC, json={"model": "m", "stream": True, "tools": TOOLS,
                                                              "messages": [{"role": "user", "content": "go"}]})
    assert "⟨API_KEY_1⟩" in _rows(client)[0]["sent_fields"]


def test_nothing_is_stored_for_what_stays_private():
    client, up = _make()
    client.post("/v1/chat/completions", headers={**PUBLIC, "x-cm-project": "confidential"},
                json={"model": "m", "tools": TOOLS, "messages": [{"role": "user", "content": "plan"}]})
    (row,) = _rows(client)
    assert row["lane"] == "standard" and row["sent_payload"] is None and row["sent_fields"] is None


def test_the_list_view_keeps_its_shape():
    client, up = _make()
    client.post("/v1/chat/completions", headers=PUBLIC, json={"model": "m", "tools": TOOLS, "messages": [{"role": "user", "content": "go"}]})
    row = client.get("/v1/ledger/requests").json()["requests"][0]
    assert "sent_payload" not in row and "sent_fields" not in row and row["has_payload"] is True
    one = client.get(f"/v1/ledger/requests/{row['id']}").json()
    assert isinstance(json.loads(one["sent_payload"]), list) and json.loads(one["sent_fields"])["tools"]


def test_an_old_ledger_file_opens_and_gains_the_column(tmp_path):
    path = tmp_path / "ledger.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, session TEXT NOT NULL,"
               " lane TEXT NOT NULL, model TEXT NOT NULL, context_label INTEGER NOT NULL,"
               " prompt_tokens INTEGER NOT NULL, cached_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,"
               " cost REAL NOT NULL, counterfactual REAL NOT NULL, masked_spans INTEGER NOT NULL, reason TEXT NOT NULL,"
               " sent_payload TEXT, chars_in INTEGER NOT NULL DEFAULT 0, chars_out INTEGER NOT NULL DEFAULT 0,"
               " billing TEXT NOT NULL DEFAULT 'paid')")
    db.execute("INSERT INTO requests (ts, session, lane, model, context_label, prompt_tokens, cached_tokens,"
               " completion_tokens, cost, counterfactual, masked_spans, reason, sent_payload)"
               " VALUES (0,'s','contributor','m',0,1,0,1,1,1,0,'','[]')")
    db.commit()
    db.close()
    ledger = Ledger(path)
    (row,) = ledger.requests(payload=True)["requests"]
    assert row["sent_payload"] == "[]" and row["sent_fields"] is None and row["has_payload"] is True
    assert ledger.request(1)["sent_fields"] is None
