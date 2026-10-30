import json
import random
import string

from compute_mint.context import Provenance, label_messages
from compute_mint.detect import find_spans, has_floor
from compute_mint.labels import Label, contributable, join
from compute_mint.pricing import Usage, cost, counterfactual_cost
from compute_mint.router import CONTRIBUTOR, STANDARD, rehydrate_response, route
from compute_mint.vault import Vault

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
EMAIL = "alice.chen@acme-corp.io"


def test_a_secret_after_a_json_escape_is_still_found():
    # Tool-call arguments are JSON text: a key on its own line has a letter right in front of it.
    for prefix in (r"\n", r"\r", r"\t", r"。", r"\\n"):
        assert has_floor(prefix + KEY), prefix
    assert has_floor(r"\nA123456789")
    assert not has_floor("task-a1B2c3D4e5F6g7H8i9J0k1L2")     # still a word start, not a substring search
    args = json.dumps({"input": f"*** Begin Patch\n{KEY}\n*** End Patch"})
    masked, n = Vault().mask(args)
    assert n == 1 and KEY not in masked and json.loads(masked)["input"].splitlines()[1] == "⟨API_KEY_1⟩"


def test_lattice_and_dial_clamp():
    assert join(Label.PUBLIC, Label.FLOOR, Label.OWN_IP) is Label.FLOOR
    assert contributable(Label.PUBLIC, Label.PUBLIC)
    assert not contributable(Label.OWN_IP, Label.PUBLIC)
    assert contributable(Label.OWN_IP, Label.OWN_IP)
    # No dial setting can make CONFIDENTIAL or FLOOR contributable.
    for dial in Label:
        assert not contributable(Label.CONFIDENTIAL, dial)
        assert not contributable(Label.FLOOR, dial)


def test_detects_credentials_and_personal_data():
    kinds = {s.kind for s in find_spans(f"key={KEY} mail {EMAIL} phone 0912-345-678")}
    assert {"API_KEY", "EMAIL", "TW_PHONE"} <= kinds
    assert find_spans("contact noreply@example.com") == []


def test_vault_is_consistent_and_reversible():
    v = Vault()
    a, n = v.mask(f"use {KEY} then {KEY} and mail {EMAIL}")
    assert n == 3 and KEY not in a and EMAIL not in a
    assert a.count("⟨API_KEY_1⟩") == 2
    assert v.rehydrate(a) == f"use {KEY} then {KEY} and mail {EMAIL}"


def test_foreign_assistant_message_inherits_taint():
    msgs = [
        {"role": "user", "content": f"my key is {KEY}"},
        {"role": "assistant", "content": "ok, noted"},
        {"role": "user", "content": "now write a sorting function"},
    ]
    labeled = label_messages(msgs, Label.PUBLIC, Provenance())
    assert labeled[1].effective is Label.FLOOR      # derived from a context that held the key
    assert labeled[2].effective is Label.PUBLIC


def test_secret_in_tool_output_is_masked_and_goes_to_contributor():
    msgs = [
        {"role": "user", "content": "why does the deploy fail?"},
        {"role": "tool", "tool_call_id": "t1", "content": f"Error: auth failed for token {KEY}"},
    ]
    d = route(msgs, baseline=Label.PUBLIC, dial=Label.PUBLIC, vault=Vault(), provenance=Provenance())
    assert d.lane == CONTRIBUTOR
    assert KEY not in str(d.messages)
    assert d.masked_spans == 1


def test_foreign_assistant_after_secret_blocks_contributor():
    msgs = [
        {"role": "user", "content": f"my key is {KEY}"},
        {"role": "assistant", "content": "I will remember the key."},
        {"role": "user", "content": "continue"},
    ]
    d = route(msgs, baseline=Label.PUBLIC, dial=Label.PUBLIC, vault=Vault(), provenance=Provenance())
    assert d.lane == STANDARD and d.blocked_by == [1]


def test_own_provenance_breaks_the_taint_cascade():
    vault, prov = Vault(), Provenance()
    first = [{"role": "user", "content": f"my key is {KEY}; explain what it is for"}]
    d1 = route(first, baseline=Label.PUBLIC, dial=Label.PUBLIC, vault=vault, provenance=prov)
    assert d1.lane == CONTRIBUTOR
    reply = rehydrate_response(
        {"choices": [{"message": {"role": "assistant", "content": "⟨API_KEY_1⟩ is an API key."}}]}, vault)
    msg = reply["choices"][0]["message"]
    assert KEY in msg["content"]                      # the user sees the real value
    prov.record(msg, d1.context_label)

    second = first + [msg, {"role": "user", "content": "now write a sorting function"}]
    d2 = route(second, baseline=Label.PUBLIC, dial=Label.PUBLIC, vault=vault, provenance=prov)
    assert d2.lane == CONTRIBUTOR and KEY not in str(d2.messages)


def test_dial_controls_own_ip():
    msgs = [{"role": "user", "content": "refactor my side project"}]
    common = dict(vault=Vault(), provenance=Provenance())
    assert route(msgs, baseline=Label.OWN_IP, dial=Label.PUBLIC, **common).lane == STANDARD
    assert route(msgs, baseline=Label.OWN_IP, dial=Label.OWN_IP, **common).lane == CONTRIBUTOR
    assert route(msgs, baseline=Label.CONFIDENTIAL, dial=Label.OWN_IP, **common).lane == STANDARD


def _rand_secret(rng: random.Random) -> str:
    pick = rng.randrange(4)
    body = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(28))
    return ["sk-" + body, "ghp_" + body + "abcdefgh", f"user{rng.randrange(999)}@corp{rng.randrange(99)}.com",
            f"09{rng.randrange(10,99)}-{rng.randrange(100,999)}-{rng.randrange(100,999)}"][pick]


def test_property_no_secret_ever_reaches_contributor():
    rng = random.Random(7)
    for _ in range(300):
        vault, prov, secrets, msgs = Vault(), Provenance(), [], []
        for _ in range(rng.randrange(1, 8)):
            role = rng.choice(["user", "tool", "assistant"])
            text = "".join(rng.choice(string.ascii_lowercase + " ") for _ in range(40))
            if rng.random() < 0.4:
                s = _rand_secret(rng)
                secrets.append(s)
                text += " " + s
            m = {"role": role, "content": text}
            if role == "tool":
                m["tool_call_id"] = "x"
            msgs.append(m)
        d = route(msgs, baseline=Label.PUBLIC, dial=rng.choice([Label.PUBLIC, Label.OWN_IP]),
                  vault=vault, provenance=prov)
        if d.lane == CONTRIBUTOR:
            sent = str(d.messages)
            assert not any(s in sent for s in secrets)


def test_prices_match_official_table():
    u = Usage(prompt_tokens=20_000, cached_tokens=15_000, completion_tokens=1_000)
    assert round(cost("muse-spark-1.3", u), 5) == 0.01275
    assert round(cost("muse-spark-1.3-contributor", u), 5) == 0.00073
    assert counterfactual_cost("muse-spark-1.3-contributor", u) == cost("muse-spark-1.3", u)
