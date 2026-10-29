"""Tool output that names no file: labels from the paths it prints and from content fingerprints."""
import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from compute_mint.app import Config, create_app
from compute_mint.fingerprint import SCORE, FingerprintIndex, extract
from compute_mint.labels import Label
from compute_mint.outpaths import paths_in_text, resolve, root_from_text
from compute_mint.policy import Policy, clean_root

ROOT = "/work/shop"
CLIENTS = ('{"clients": [{"name": "Zorbel Quillmark Co.", "contact": "Hanne Voskuijlen", "tax_id": "TW90210017", '
           '"rate": "0.0731"}, {"name": "Ferrowick Fabrics Ltd.", "contact": "Odile Brandvold", "tax_id": "TW90210023"}]}')
PYTEST_FAIL = (
    "F. [100%]\n=== FAILURES ===\n___ test_reminder ___\n\n"
    "clients = [{'contact': 'Hanne Voskuijlen', 'name': 'Zorbel Quillmark Co.'}]\n\n"
    "    def test_reminder(clients):\n>       assert 'day' in text\nE       AssertionError\n\n"
    "tests/test_notify.py:15: AssertionError\nFAILED tests/test_notify.py::test_reminder\n1 failed, 2 passed in Xs\n")
PYTEST_PLAIN = ("F. [100%]\n=== FAILURES ===\n___ test_total ___\n\n    def test_total():\n>       assert add(1, 2) == 4\n"
                "E       assert 3 == 4\n\ntests/test_notify.py:15: AssertionError\n1 failed, 1 passed in Xs\n")


def refs(text, command=False):
    return [r.path for r in paths_in_text(text, command)]


# ---- path extraction -------------------------------------------------------------------------------

def test_python_traceback_and_quoted_file_names():
    text = ('Traceback (most recent call last):\n  File "/work/app/shop/clients.py", line 12, in find\n    x\n'
            '  File "<string>", line 1\n  File "my docs/notes.py", line 3\nKeyError: 1')
    assert refs(text) == ["/work/app/shop/clients.py", "my docs/notes.py"]


def test_path_line_pytest_node_ids_and_compilers():
    assert refs("tests/test_a.py:15: AssertionError\nFAILED tests/test_a.py::TestX::test_y - assert 1\n") == ["tests/test_a.py"]
    assert refs("./main.go:12:3: undefined: foo\n --> src/main.rs:3:5\nsrc/a.ts(12,5): error TS2322") == \
        ["main.go", "src/main.rs", "src/a.ts"]
    assert refs("grep hit contracts/acme-msa.md:3:net 45 and shop/clients.py:14:    def find") == \
        ["contracts/acme-msa.md", "shop/clients.py"]


def test_windows_and_backslash_paths():
    assert refs(r"C:\proj\src\a.py:12: error and tests\test_x.py:5") == ["C:/proj/src/a.py", "tests/test_x.py"]


def test_git_diff_headers_drop_the_a_b_prefix():
    assert refs("diff --git a/shop/x.py b/shop/x.py\n--- a/shop/x.py\n+++ b/shop/x.py\n@@ -1 +1 @@") == ["shop/x.py"]


def test_prose_urls_versions_and_emails_are_not_paths():
    text = ("and/or 1.5/2.0 2026/10/21 see https://example.com/a/b.py or e.g. input/output; ap@quill.example; "
            "os.path; N/A; java.base/java.lang.Thread.run; version 3.12.6")
    assert refs(text) == []


def test_bare_file_names_count_only_with_a_line_number_or_in_a_command():
    assert refs("error in main.py") == []
    assert refs("main.py:12: boom") == ["main.py"]
    assert [(r.path, r.dirless) for r in paths_in_text("cat .env && python app.py os.path", command=True)] == \
        [(".env", True), ("app.py", True)]
    assert refs("python tool.py --config=conf/prod.yml ../other/x.py", command=True) == ["tool.py", "conf/prod.yml", "../other/x.py"]


def test_library_code_is_marked():
    (ref,) = paths_in_text('File "/usr/lib/python3.12/site-packages/_pytest/x.py", line 3')
    assert ref.library


def test_resolve_and_root_hints():
    (ref,) = paths_in_text("tests/test_a.py:1: E")
    assert resolve(ref, "/work/shop") == "/work/shop/tests/test_a.py"
    assert resolve(ref, None) is None
    (up,) = paths_in_text("../other/x.py:1: E")
    assert resolve(up, "/work/shop") == "/work/other/x.py"
    assert root_from_text("The repository root is /work/shop.") == "/work/shop"
    assert root_from_text("Primary working directory: C:\\Users\\u\\proj\nmore") == "C:/Users/u/proj"
    assert root_from_text("<cwd>/home/u/p</cwd>") == "/home/u/p"
    assert root_from_text("Working directory is /w/x/y, git repo: yes") == "/w/x/y"
    assert root_from_text("Run it from /usr/bin") is None
    assert clean_root("relative/dir") is None and clean_root("/work/shop/") == "/work/shop"


# ---- fingerprints ----------------------------------------------------------------------------------

def test_extract_finds_names_ids_and_decimals_and_skips_common_words():
    terms = extract(CLIENTS)
    for expected in ("zorbel", "quillmark", "zorbel quillmark", "hanne voskuijlen", "voskuijlen", "tw90210017", "0.0731"):
        assert expected in terms, expected
    for ordinary in ("clients", "contact", "name", "rate", "customer", "payment", "statement"):
        assert ordinary not in terms


def test_prose_contributes_proper_nouns_not_ordinary_vocabulary():
    prose = ("Overview. Reconciliation procedures are handled by the Zorbel Quillmark account team. "
             "Escalation happens through Mortenson when a settlement dispute arises; remittance advice follows.")
    terms = extract(prose, prose=True)
    assert "mortenson" in terms and "zorbel quillmark" in terms
    assert "reconciliation" not in terms and "escalation" not in terms and "settlement" not in terms
    assert "reconciliation" in extract(prose, prose=False)       # structured data keeps every unusual word


def test_source_code_contributes_string_literals_not_identifiers():
    code = 'def find_overdue_ledger_entries(accounts):\n    """Docstring about ledgers."""\n    return load("Zorbel Quillmark Co.", 0.0731)\n'
    terms = extract(code, code=True)
    assert "zorbel quillmark" in terms and "0.0731" in terms
    assert not any("ledger" in t for t in terms)


def test_hits_need_a_score_of_two():
    idx = FingerprintIndex()
    idx.add("/w/clients.json", CLIENTS)
    exempt = frozenset()
    score = lambda text: sum(SCORE[m.kind] for m in idx.matches(text, exempt))
    assert score("Dear Hanne Voskuijlen, your invoice is overdue") >= 2
    assert score("quillmark") >= 2                               # one unusual word is enough
    assert score("The contact person is Hanne") < 2              # a weak first name alone is not
    assert score("TW90210017") >= 2 and score("rate 0.0731 applies") >= 2


def test_an_unreviewed_source_only_counts_names_and_identifiers():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    data = '{"vendor": "reconciliation settlement remittance", "tag": "Quillmark"}'
    ordinary = "reconciliation settlement remittance escalation"
    # unreviewed: a plain unusual word is not enough evidence
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/data/vendors.json"), tool("r", data)])
    text = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_PLAIN + "quillmark " + ordinary)]
    assert labels_of(p, text)[0][3] == Label.OWN_IP
    # reviewed as confidential: the same word now counts
    p.set_rule(f"{ROOT}/data/**", Label.CONFIDENTIAL)
    assert labels_of(p, text)[0][3] == Label.CONFIDENTIAL
    # a name is evidence even before the review
    q = Policy()
    q.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    labels_of(q, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    assert labels_of(q, base_messages() + [call("a", "run_tests"), tool("a", PYTEST_FAIL)])[0][3] == Label.CONFIDENTIAL


def test_public_text_is_not_matched():
    idx = FingerprintIndex()
    idx.add("/w/clients.json", CLIENTS)
    idx.add("/w/contract.md", "Payment terms: net 45 days from the statement date. The supplier shall invoice monthly. "
                              "Late payment accrues interest. Contact the account manager to dispute a statement.")
    public = [
        "def slugify(text, max_length=80):\n    return text.lower().replace(' ', '-')[:max_length]",
        "FAILED tests/test_slug.py::test_max_length - assert 'hello-wo' == 'hello-world'\n1 failed, 14 passed in Xs",
        "Dear customer, your invoice is overdue. Please arrange payment or contact accounts receivable.",
        "The statement above is correct; payment terms are listed in the contract and the supplier invoices monthly.",
        "Traceback (most recent call last):\n  File \"app.py\", line 3, in <module>\nZeroDivisionError: division by zero",
        "Usage: tool [options] FILE\n  --verbose  print more\n  --config=PATH  read settings from PATH",
    ]
    for text in public:
        assert sum(SCORE[m.kind] for m in idx.matches(text)) < 2, text


def test_words_the_caller_supplied_are_exempt():
    idx = FingerprintIndex()
    idx.add("/w/clients.json", CLIENTS)
    exempt = idx.exempt_set("Please fix the Zorbel Quillmark reminder")
    assert idx.matches("Zorbel Quillmark Co.", exempt) == []
    assert idx.matches("Ferrowick Fabrics Ltd.", exempt) != []


def test_the_index_keeps_no_plain_terms():
    idx = FingerprintIndex()
    idx.add("/w/clients.json", CLIENTS)
    blob = repr(idx) + repr(vars(idx))
    for secret in ("zorbel", "quillmark", "voskuijlen", "tw90210017", "0.0731", "Hanne"):
        assert secret.lower() not in blob.lower()
    assert len(idx) > 5
    other = FingerprintIndex()
    other.add("/w/clients.json", CLIENTS)
    assert set(idx._terms) != set(other._terms)       # keyed per index: hashes are not portable


def test_adding_the_same_text_twice_is_a_noop():
    idx = FingerprintIndex()
    assert idx.add("/w/c.json", CLIENTS) > 0 and idx.add("/w/c.json", CLIENTS) == 0


# ---- policy ----------------------------------------------------------------------------------------

def call(id_, name, **args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def tool(id_, text):
    return {"role": "tool", "tool_call_id": id_, "content": text}


def base_messages():
    return [{"role": "system", "content": f"You are an agent. The repository root is {ROOT}."},
            {"role": "user", "content": "Fix the reminder wording in shop/notify.py"}]


def labels_of(policy, messages, default=Label.OWN_IP, root=None):
    b = policy.baseline_for(messages, default, root=root)
    return [b(i, m) for i, m in enumerate(messages)], b


def test_output_paths_are_judged_by_the_rules_and_unreviewed_means_confidential():
    p = Policy()
    msgs = base_messages() + [call("a", "run_tests", target="tests/test_notify.py"), tool("a", PYTEST_PLAIN)]
    labels, b = labels_of(p, msgs)
    assert labels[3] == Label.CONFIDENTIAL and b.why(3) == ("output-path",)
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    assert labels_of(p, msgs)[0][3] == Label.OWN_IP
    p.set_rule(f"{ROOT}/tests/test_notify.py", Label.FLOOR)         # strictest rule wins
    assert labels_of(p, msgs)[0][3] == Label.FLOOR


def test_a_traceback_through_a_sensitive_file_is_sensitive_even_when_the_test_file_is_fine():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    p.set_rule(f"{ROOT}/shop/**", Label.OWN_IP)
    p.set_rule(f"{ROOT}/config/**", Label.CONFIDENTIAL)
    text = PYTEST_PLAIN + f'  File "{ROOT}/config/secrets_loader.py", line 4, in load\n'
    msgs = base_messages() + [call("a", "run_tests"), tool("a", text)]
    assert labels_of(p, msgs)[0][3] == Label.CONFIDENTIAL


def test_relative_paths_are_placed_with_root_cwd_header_or_seen_paths():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.PUBLIC)
    p.set_rule("/elsewhere/tests/**", Label.OWN_IP)
    out = [call("a", "bash", command="pytest -q"), tool("a", PYTEST_PLAIN)]
    # root from the system prompt
    assert labels_of(p, base_messages() + out, default=Label.PUBLIC)[0][3] == Label.PUBLIC
    # the call's own working directory wins over the prompt
    cwd = [call("a", "bash", command="pytest -q", workdir="/elsewhere"), tool("a", PYTEST_PLAIN)]
    assert labels_of(p, base_messages() + cwd, default=Label.PUBLIC)[0][3] == Label.OWN_IP
    # the x-cm-root header wins over the prompt
    no_root = [{"role": "user", "content": "run the tests"}] + out
    assert labels_of(p, no_root, default=Label.PUBLIC, root="/work/shop")[0][2] == Label.PUBLIC
    # no root anywhere and nothing seen: fail closed
    assert labels_of(p, no_root, default=Label.PUBLIC)[0][2] == Label.CONFIDENTIAL
    # a path named by an earlier call places the relative one
    seen = [{"role": "user", "content": "run the tests"}, call("r", "read_file", path=f"{ROOT}/tests/test_notify.py"),
            tool("r", "x"), call("a", "bash", command="pytest -q"), tool("a", PYTEST_PLAIN)]
    assert labels_of(p, seen, default=Label.PUBLIC)[0][4] == Label.PUBLIC


def test_command_arguments_name_paths_too():
    p = Policy()
    p.set_rule(f"{ROOT}/contracts/**", Label.CONFIDENTIAL)
    msgs = base_messages() + [call("a", "shell", command=["bash", "-lc", "cat contracts/acme.md"]), tool("a", "Net 45 days")]
    assert labels_of(p, msgs, default=Label.PUBLIC)[0][3] == Label.CONFIDENTIAL


def test_library_frames_do_not_taint_or_flood_the_queue():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    text = ('File "/usr/lib/python3.12/site-packages/_pytest/runner.py", line 3\n'
            'File "/home/u/.venv/lib/python3.12/site-packages/pluggy/_hooks.py", line 9\n' + PYTEST_PLAIN)
    msgs = base_messages() + [call("a", "run_tests"), tool("a", text)]
    assert labels_of(p, msgs)[0][3] == Label.OWN_IP
    assert p.enqueue_unknown(msgs, [3]) == 0


def test_a_file_read_is_labeled_by_that_file_not_by_the_paths_it_mentions():
    p = Policy()
    p.set_rule(f"{ROOT}/docs/**", Label.PUBLIC)
    doc = "The loader lives in config/secrets_loader.py and reads contracts/acme.md."
    msgs = base_messages() + [call("a", "read_file", path=f"{ROOT}/docs/api.md"), tool("a", doc)]
    assert labels_of(p, msgs, default=Label.PUBLIC)[0][3] == Label.PUBLIC


def test_unreviewed_output_paths_join_the_review_queue():
    p = Policy()
    msgs = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_PLAIN)]
    assert p.enqueue_unknown(msgs, [3]) == 1
    assert p.pending()[0]["path"] == f"{ROOT}/tests/test_notify.py"
    assert p.pending()[0]["suggested_pattern"] == f"{ROOT}/tests/**"


def test_fingerprints_carry_a_read_into_later_tool_output():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    read = [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)]
    first = base_messages() + read
    labels_of(p, first)                                                    # the read is remembered (unreviewed = confidential)
    later = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_FAIL)]
    labels, b = labels_of(p, later)
    assert labels[3] == Label.CONFIDENTIAL and "fingerprint" in b.why(3)
    clean = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_PLAIN)]
    assert labels_of(p, clean)[0][3] == Label.OWN_IP                       # same test file, no sensitive text: not blocked


def test_a_review_decision_switches_the_fingerprints_of_that_file_off():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    later = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_FAIL)]
    assert labels_of(p, later)[0][3] == Label.CONFIDENTIAL
    p.set_rule(f"{ROOT}/config/**", Label.OWN_IP)
    assert labels_of(p, later)[0][3] == Label.OWN_IP
    p.set_rule(f"{ROOT}/config/clients.json", Label.CONFIDENTIAL)
    assert labels_of(p, later)[0][3] == Label.CONFIDENTIAL


def test_the_review_queue_lists_what_holds_back_most_first_when_output_paths_are_on():
    msgs = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_PLAIN)]
    other = base_messages() + [call("r", "read_file", path=f"{ROOT}/docs/once.md"), tool("r", "x")]
    p = Policy()
    p.enqueue_unknown(other, [3])
    for _ in range(3):
        p.enqueue_unknown(msgs, [3])
    assert [q["path"] for q in p.pending()] == [f"{ROOT}/tests/test_notify.py", f"{ROOT}/docs/once.md"]
    assert p.pending()[0]["hits"] == 3
    fifo = Policy(output_paths=False)
    fifo.enqueue_unknown(other, [3])
    fifo.enqueue_unknown(base_messages() + [call("r", "read_file", path=f"{ROOT}/a.md"), tool("r", "x")], [3])
    for _ in range(3):
        fifo.enqueue_unknown(base_messages() + [call("r", "read_file", path=f"{ROOT}/a.md"), tool("r", "x")], [3])
    assert [q["path"] for q in fifo.pending()] == [f"{ROOT}/docs/once.md", f"{ROOT}/a.md"]    # first seen first


def test_files_that_are_not_sensitive_are_never_remembered():
    p = Policy()
    p.set_rule(f"{ROOT}/config/**", Label.OWN_IP)
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    assert len(p.index) == 0
    later = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_FAIL)]
    assert labels_of(p, later)[0][3] == Label.OWN_IP


def test_reading_a_file_by_its_path_ignores_fingerprints():
    p = Policy()
    p.set_rule(f"{ROOT}/config/**", Label.CONFIDENTIAL)
    p.set_rule(f"{ROOT}/shop/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    code = 'GREETING = "Dear Hanne Voskuijlen"\n'      # a file the user labeled OWN_IP that happens to repeat a name
    msgs = base_messages() + [call("c", "read_file", path=f"{ROOT}/shop/notify.py"), tool("c", code)]
    assert labels_of(p, msgs)[0][3] == Label.OWN_IP


def test_a_pasted_name_in_a_later_user_message_is_caught_but_the_first_prompt_is_not():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    first = [{"role": "system", "content": "agent"}, {"role": "user", "content": "Why was Zorbel Quillmark Co. billed twice?"}]
    assert labels_of(p, first)[0][1] == Label.OWN_IP
    follow = first + [{"role": "assistant", "content": "Looking."}, {"role": "user", "content": "Also check Ferrowick Fabrics Ltd."}]
    assert labels_of(p, follow)[0][3] == Label.CONFIDENTIAL


def test_the_prompts_own_words_are_not_evidence():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    out = PYTEST_FAIL.replace("Hanne Voskuijlen", "someone")
    msgs = [{"role": "system", "content": f"The repository root is {ROOT}."},
            {"role": "user", "content": "tests fail for Zorbel Quillmark Co., fix it"}, call("a", "run_tests"), tool("a", out)]
    assert labels_of(p, msgs)[0][3] == Label.OWN_IP                    # the user already said it
    other = [msgs[0], {"role": "user", "content": "tests fail, fix it"}, call("a", "run_tests"), tool("a", out)]
    assert labels_of(p, other)[0][3] == Label.CONFIDENTIAL             # without the prompt's help the name is evidence


def test_switches_turn_the_two_mechanisms_off():
    msgs = base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS),
                              call("a", "run_tests"), tool("a", PYTEST_FAIL)]
    off = Policy(output_paths=False, fingerprints=False)
    assert labels_of(off, msgs)[0][5] == Label.OWN_IP
    only_paths = Policy(fingerprints=False)
    assert labels_of(only_paths, msgs)[0][5] == Label.CONFIDENTIAL and only_paths.index is None


# ---- through the proxy -----------------------------------------------------------------------------

class Agent:
    """Drives the proxy like an agent: the model asks for a tool, the tool answers, the loop continues.
    The upstream is scripted, so the assistant turn in the history is a reply the gateway produced."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.next_call: dict | None = None

        def upstream(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.sent.append(body)
            msg = {"role": "assistant", "content": "ok"}
            if self.next_call:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": self.next_call["name"],
                                                                  "arguments": json.dumps(self.next_call["args"])}}]}
                self.next_call = None
            return httpx.Response(200, json={"id": "x", "object": "chat.completion", "model": body["model"],
                                             "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                             "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
        self.app = create_app(Config(api_base="https://mock/v1", api_key="test", billing="paid"), transport=httpx.MockTransport(upstream))
        self.client = TestClient(self.app)

    def post(self, session, messages, root=ROOT):
        headers = {"x-cm-session": session, "x-cm-project": "own_ip", "x-cm-dial": "own_ip"}
        if root:
            headers["x-cm-root"] = root
        return self.client.post("/v1/chat/completions", json={"model": "m", "messages": messages}, headers=headers)

    def tool_turn(self, session, prompt, name, args, output, root=ROOT):
        """prompt -> model asks for a tool -> tool output -> model; returns the lane of the request carrying the output."""
        messages = [{"role": "system", "content": "You are an agent."}, {"role": "user", "content": prompt}]
        self.next_call = {"name": name, "args": args}
        first = self.post(session, messages, root)
        assert first.headers["x-cm-lane"] == "contributor"
        messages += [first.json()["choices"][0]["message"], {"role": "tool", "tool_call_id": "c1", "content": output}]
        return self.post(session, messages, root).headers["x-cm-lane"]


def test_end_to_end_names_read_in_one_session_do_not_leak_through_test_output_in_another():
    agent = Agent()
    agent.app.state.policy.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    # session A: the agent reads the customer list (unreviewed: confidential, Standard)
    assert agent.tool_turn("A", "Fix the reminder wording", "read_file", {"path": f"{ROOT}/config/clients.json"}, CLIENTS) == "standard"
    # session B: a failing test prints the names; the call names no file
    assert agent.tool_turn("B", "Fix the reminder wording", "run_tests", {}, PYTEST_FAIL) == "standard"
    # the same test file failing without those names is still contributable
    assert agent.tool_turn("C", "Fix the sum", "run_tests", {}, PYTEST_PLAIN) == "contributor"
    contributor = [c for c in agent.sent if c["model"].endswith("contributor")]
    assert contributor and all("Voskuijlen" not in json.dumps(c) and "Zorbel" not in json.dumps(c) for c in contributor)


def test_end_to_end_unreviewed_test_file_waits_for_review_then_flows():
    agent = Agent()
    assert agent.tool_turn("s", "Run the tests", "run_tests", {}, PYTEST_PLAIN) == "standard"
    queue = agent.client.get("/v1/review").json()["pending"]
    assert [q["path"] for q in queue] == [f"{ROOT}/tests/test_notify.py"]
    assert agent.client.post(f"/v1/review/{queue[0]['id']}", json={"label": "own_ip"}).status_code == 200
    assert agent.tool_turn("s2", "Run the tests", "run_tests", {}, PYTEST_PLAIN) == "contributor"


def test_end_to_end_the_root_comes_from_the_system_prompt_when_no_header_is_sent():
    agent = Agent()
    agent.app.state.policy.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    messages = [{"role": "system", "content": f"You are an agent. Working directory: {ROOT}"}, {"role": "user", "content": "Run the tests"}]
    agent.next_call = {"name": "run_tests", "args": {}}
    first = agent.post("p", messages, root=None)
    messages += [first.json()["choices"][0]["message"], {"role": "tool", "tool_call_id": "c1", "content": PYTEST_PLAIN}]
    assert agent.post("p", messages, root=None).headers["x-cm-lane"] == "contributor"


def test_fingerprints_never_reach_the_ledger_or_the_policy_database():
    agent = Agent()
    agent.tool_turn("A", "x", "read_file", {"path": f"{ROOT}/config/clients.json"}, CLIENTS)
    rows = agent.app.state.ledger.db.execute("SELECT * FROM requests").fetchall()
    assert "quillmark" not in json.dumps(rows, default=str).lower()
    dump = " ".join(agent.app.state.policy.db.iterdump())
    assert "quillmark" not in dump.lower() and "voskuijlen" not in dump.lower()


# ---- the gateway must not know the bench ------------------------------------------------------------

def test_gateway_source_has_no_bench_specific_knowledge():
    pkg = Path(__file__).resolve().parent.parent / "compute_mint"
    text = "\n".join(p.read_text(encoding="utf-8").lower() for p in sorted(pkg.iterdir()) if p.suffix in {".py", ".txt"})
    for needle in ("canar", "billflow", "slugkit", "bench"):
        assert needle not in text, needle
    assert "import bench" not in text and "from bench" not in text


def test_no_planted_value_of_the_bench_appears_in_the_gateway():
    bench = Path(__file__).resolve().parents[2] / "bench" / "materials"
    files = sorted(bench.glob("*/canaries.json"))
    if not files:
        pytest.skip("bench materials not present")
    pkg = Path(__file__).resolve().parent.parent / "compute_mint"
    text = "\n".join(p.read_text(encoding="utf-8").lower() for p in sorted(pkg.iterdir()) if p.suffix in {".py", ".txt"})
    canaries = [c for f in files for c in json.loads(f.read_text(encoding="utf-8"))["canaries"]]
    assert canaries
    assert [c["value"] for c in canaries if c["value"].lower() in text] == []
    # the words of planted names must not be in the stoplist or the sources either
    words = {w for c in canaries if c["kind"] in {"customer_name", "person_name"}
             for w in re.findall(r"[a-z0-9]+", c["value"].lower()) if len(w) >= 4}
    vocabulary = set(re.findall(r"[a-z0-9]+", text))
    assert not [w for w in words if w in vocabulary], "a planted name is known to the gateway"


def test_terms_of_a_cleared_file_stop_counting():
    p = Policy()
    p.set_rule(f"{ROOT}/tests/**", Label.OWN_IP)
    p.set_rule(f"{ROOT}/shop/**", Label.OWN_IP)
    labels_of(p, base_messages() + [call("r", "read_file", path=f"{ROOT}/config/clients.json"), tool("r", CLIENTS)])
    later = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_FAIL)]
    assert labels_of(p, later)[0][3] == Label.CONFIDENTIAL
    # the user's own OWN_IP code mentions the company name: that name is allowed out, the contact is still not
    code = 'FOOTER = "Zorbel Quillmark Co. Accounts Receivable"\n'
    labels_of(p, base_messages() + [call("c", "read_file", path=f"{ROOT}/shop/notify.py"), tool("c", code)])
    name_only = base_messages() + [call("a", "run_tests"), tool("a", PYTEST_PLAIN + "Zorbel Quillmark Co.")]
    assert labels_of(p, name_only)[0][3] == Label.OWN_IP
    assert labels_of(p, later)[0][3] == Label.CONFIDENTIAL        # the contact name is still evidence


def test_escape_sequences_in_a_repr_are_not_windows_paths():
    text = r"assert '1 day' in 'Dear Ines,\n\nInvoice INV-1 is overdue.\tPlease pay' and C:\new\test.py:3: E"
    assert refs(text) == ["C:/new/test.py"]
