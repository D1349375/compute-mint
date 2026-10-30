"""Demo data for the dashboard, made without a Meta API key and without any network.

Scripted agent sessions over the two invented repositories in `bench/materials/` (slugkit, a public
library; billflow, a fictional company's invoicing service) are sent through the real gateway
(`create_app`), whose upstream is an `httpx.MockTransport` playing a scripted model. The gateway
writes its ledger and policy (learned rules, review queue) to two SQLite files; start the gateway
on the same files and the dashboard shows them. No real session content is used anywhere.

Three phases, so every lane appears:
  1. paid billing (comparison only): what may not go to Contributor goes to Standard;
  2. credits, no local model: it is held (403);
  3. credits with a local model: it runs locally.
Between phases 2 and 3 two review decisions are made (slugkit's code and tests are public), so the
same task that was held in phase 2 is contributed in phase 3. Pending review items are left for the
live demo; `--replay` then resends the sessions behind them.

    cd gateway
    .venv/Scripts/python -m demo.seed --out ../dashboard/demo-data
    .venv/Scripts/python -m demo.seed --out ../dashboard/demo-data --replay     # after deciding in the dashboard
"""
import argparse
import hashlib
import json
import random
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from compute_mint import ledger as ledger_module
from compute_mint.app import Config, create_app
from compute_mint.labels import Label

MATERIALS = Path(__file__).resolve().parents[2] / "bench" / "materials"
META_HOST, LOCAL_HOST = "mock-meta", "mock-local"
# Built at run time so no secret scanner matches this file. The value is invented.
FAKE_KEY = "sk-" + "demo" + "Q7wE2rT9yU4iO1pA6sD3fG8h"

SYSTEM = """You are a careful coding agent working inside a single repository. Tool paths are absolute and \
live under the repository root.

How to work:
1. Understand the request before you change anything. Read the code you are about to modify and the tests that cover it.
2. Make the smallest change that solves the problem and keep the existing style: naming, docstrings, comment density.
3. When you change behaviour, run the relevant tests before and after, and report what the run showed.
4. Do not edit tests to make them pass. If a test looks wrong, say so in your answer instead.
5. Never print, copy or write secrets, tokens, passwords or personal data into files or into your answer. If you must \
refer to such a value, name the variable or field that holds it.
6. If a tool output was shortened and you need the missing part, read the file again.

When the work is done, reply with a short plain-text summary: what you changed or found, which files are involved and \
what the final test run showed. Do not call a tool in that reply.

The repository root is {root}."""


def _tool(name: str, description: str, **params: str) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "required": list(params),
                       "properties": {k: {"type": "string", "description": v} for k, v in params.items()}}}}


TOOLS = [
    _tool("list_files", "List the files under a directory, recursively, with sizes.",
          directory="absolute directory path"),
    _tool("read_file", "Return the full text of a file.", path="absolute file path"),
    _tool("write_file", "Create or overwrite a file with its complete new content.",
          path="absolute file path", content="the complete new file content"),
    _tool("run_tests", "Run pytest in the repository root.", target="the usual pytest arguments"),
]


# -- mock upstream ----------------------------------------------------------------------------------

class ScriptedModel:
    """Plays the model behind both hosts. The driver sets `next` before each request; usage is a
    character-based token estimate with a longest-common-prefix cache per model (as in bench/)."""

    def __init__(self) -> None:
        self.next: dict = {"role": "assistant", "content": "Done."}
        self.calls: list[tuple[str, dict]] = []
        self._prompts: dict[str, list[str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.host, body))
        prompt = json.dumps(body.get("tools", []), sort_keys=True) + "".join(
            json.dumps(m, ensure_ascii=False, sort_keys=True) for m in body["messages"])
        seen = self._prompts.setdefault(body["model"], [])
        common = max((_common_prefix(prompt, p) for p in seen), default=0)
        seen.append(prompt)
        prompt_tokens = _tokens(prompt) + 4 * len(body["messages"])
        cached = min(_tokens(prompt[:common]) // 64 * 64, prompt_tokens - 1)
        reply = json.loads(json.dumps(self.next))
        return httpx.Response(200, json={
            "id": "demo", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "message": reply, "finish_reason": "tool_calls" if reply.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": _tokens(json.dumps(reply)) + 8,
                      "prompt_tokens_details": {"cached_tokens": max(cached, 0)}}})


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return int(ascii_chars / 3.5) + (len(text) - ascii_chars)


# -- scripted sessions ------------------------------------------------------------------------------

def read(repo: str, rel: str) -> str:
    parts = rel.split("/")
    parts[-1] = parts[-1].replace(".env", "_dot_env") if parts[-1].startswith(".env") else parts[-1]
    return (MATERIALS / repo / "files" / "/".join(parts)).read_text(encoding="utf-8")


def call(name: str, **args) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{name}_{hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]}",
         "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


def say(text: str) -> dict:
    return {"role": "assistant", "content": text}


SLUG_TEST_RUN = """============================= test session starts =============================
collected 4 items

tests/test_slug.py ...F                                                  [100%]

================================== FAILURES ===================================
_________________ test_max_length_never_ends_with_separator __________________
    def test_max_length_never_ends_with_separator():
>       assert slugify("Hello, World! Again", max_length=12) == "hello-world"
E       AssertionError: assert 'hello-world-' == 'hello-world'
tests/test_slug.py:17: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_slug.py::test_max_length_never_ends_with_separator
========================= 1 failed, 3 passed in 0.03s =========================
"""

SLUG_TEST_PASS = """============================= test session starts =============================
collected 4 items

tests/test_slug.py ....                                                  [100%]

============================== 4 passed in 0.02s ==============================
"""

NOTIFY_TEST_RUN = """============================= test session starts =============================
collected 3 items

tests/test_notify.py ..F                                                 [100%]

================================== FAILURES ===================================
__________________________ test_one_day_is_singular ___________________________
E       AssertionError: assert '1 day overdue' in 'Dear Ines Varga,\\n\\nInvoice INV-1 for Quillfeather Provisions Co. is 1 days overdue.\\n'
tests/test_notify.py:15: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_notify.py::test_one_day_is_singular
========================= 1 failed, 2 passed in 0.05s =========================
"""


def run_tool(repo: str, name: str, args: dict) -> str:
    root = f"/work/{repo}/"
    if name == "read_file":
        return read(repo, args["path"].removeprefix(root))
    if name == "run_tests":
        return {"tests/test_slug.py": SLUG_TEST_RUN, "tests/test_slug.py -q": SLUG_TEST_PASS,
                "tests/test_notify.py": NOTIFY_TEST_RUN}[args["target"]]
    if name == "write_file":
        return f"wrote {len(args.get('content', ''))} characters to {args['path']}"
    raise ValueError(name)


SLUG_FIX = read("slugkit", "slugkit/slug.py").replace("slug = slug[:max_length]",
                                                      "slug = slug[:max_length].rstrip(sep)")

# (session id, repo, project, dial, client, prompt, earlier history, scripted replies). A reply that
# calls a tool is followed by that tool's output; the session ends at the first held request.
PAID = [
    ("billflow-tax-rounding", "billflow", "own_ip", "own_ip", "unknown",
     "Invoice tax is off by one cent on some totals. Find out why.", [],
     [call("read_file", path="/work/billflow/billflow/invoice.py"),
      say("Tax is rounded on every line and then summed; round once on the invoice total instead.")]),
    ("slugkit-explain-nfkd", "slugkit", "public", "public", "unknown",
     "What is the difference between NFKD and NFC normalization, in two sentences?", [],
     [say("NFC composes characters into their shortest canonical form; NFKD decomposes them and also folds "
          "compatibility variants, which is why it is used before stripping accents.")]),
]

CREDITS_HELD = [
    ("slugkit-slug-maxlen", "slugkit", "public", "public", "unknown",
     "slugify(..., max_length=12) sometimes returns a slug that ends with '-'. Fix it.", [],
     [call("read_file", path="/work/slugkit/slugkit/slug.py"), say("unreachable")]),
    ("slugkit-publish-401", "slugkit", "public", "public", "unknown",
     f"Publishing fails with: 401 Unauthorized for token {FAKE_KEY}. What is wrong?", [],
     [call("read_file", path="/work/slugkit/.env"), say("unreachable")]),
    ("billflow-currency-email", "billflow", "own_ip", "own_ip", "unknown",
     "The customer at ap@quillfeather.example (phone 0900-000-017) says invoice INV-2041 shows the wrong "
     "currency. Where does billflow pick the currency?", [],
     [call("read_file", path="/work/billflow/billflow/money.py"), say("unreachable")]),
    ("slugkit-resumed-from-claude", "slugkit", "public", "public", "anthropic",
     "Continue where we left off: add the CHANGELOG entry.",
     [{"role": "user", "content": "Plan the 0.3.0 release notes."},
      {"role": "assistant", "content": "Sure. I would group the changes into fixes and features."}],
     [say("unreachable")]),
    ("slugkit-run-tests", "slugkit", "public", "public", "unknown",
     "Run the slug tests and tell me what fails.", [],
     [call("run_tests", target="tests/test_slug.py"), say("unreachable")]),
]

CREDITS_LOCAL = [
    ("slugkit-slug-maxlen-again", "slugkit", "public", "public", "unknown",
     "slugify(..., max_length=12) sometimes returns a slug that ends with '-'. Fix it.", [],
     [call("read_file", path="/work/slugkit/slugkit/slug.py"),
      call("read_file", path="/work/slugkit/tests/test_slug.py"),
      call("run_tests", target="tests/test_slug.py"),
      call("write_file", path="/work/slugkit/slugkit/slug.py", content=SLUG_FIX),
      call("run_tests", target="tests/test_slug.py -q"),
      say("Cutting at max_length could leave a trailing separator; the slug is now stripped after the cut. "
          "tests/test_slug.py: 4 passed.")]),
    ("billflow-notify-singular", "billflow", "own_ip", "own_ip", "unknown",
     "Overdue reminders say '1 days overdue'. Fix the plural.", [],
     [call("read_file", path="/work/billflow/billflow/notify.py"),
      call("run_tests", target="tests/test_notify.py"),
      say("The unit is always 'days'; use 'day' when days_overdue is 1. The singular test now passes.")]),
    ("billflow-client-terms", "billflow", "own_ip", "own_ip", "unknown",
     "Which payment terms do our clients use? Count them per term.", [],
     [call("read_file", path="/work/billflow/config/clients.json"),
      say("net30: 1, net45: 1, net30eom: 1, net60: 1, eom: 1.")]),
    ("slugkit-docs-usage", "slugkit", "public", "public", "unknown",
     "Does the usage guide describe max_length correctly?", [],
     [call("read_file", path="/work/slugkit/docs/usage.md"),
      say("Yes: it says a slug cut by max_length never ends with the separator, which the fix now guarantees.")]),
    ("billflow-shared-chunked", "billflow", "public", "public", "unknown",
     "chunked() in shared/textutil.py drops the last short chunk. Why?", [],
     [call("read_file", path="/work/billflow/shared/textutil.py"),
      say("The range stops at len(items) - size + 1, so a shorter final chunk is never started.")]),
    ("slugkit-explain-semver", "slugkit", "public", "public", "unknown",
     "Explain in one paragraph why '1.10.0' must sort after '1.9.0'.", [],
     [say("Version parts are numbers, not text: compared as integers 10 > 9, while a string comparison "
          "looks at the character '1' versus '9' and gets it backwards.")]),
]

# Resent by --replay: the sessions whose files are left in the review queue.
REPLAY = [s for s in CREDITS_LOCAL if s[0] in ("slugkit-docs-usage", "billflow-shared-chunked")]

# Decisions the user made between phases 2 and 3 (pattern -> label).
EARLIER_REVIEWS = {"/work/slugkit/slugkit/**": Label.PUBLIC, "/work/slugkit/tests/**": Label.PUBLIC}


class Clock:
    """Stands in for time.time() in the ledger so the seeded timeline spans a few hours."""

    def __init__(self, start: float, rng: random.Random) -> None:
        self.now, self.rng = start, rng

    def time(self) -> float:
        self.now += self.rng.uniform(12, 75)
        return self.now

    def gap(self, minutes: tuple[int, int]) -> None:
        self.now += self.rng.uniform(*minutes) * 60


@contextmanager
def ledger_clock(clock):
    original = ledger_module.time
    ledger_module.time = clock or time
    try:
        yield
    finally:
        ledger_module.time = original


def run_sessions(client: TestClient, model: ScriptedModel, sessions, clock: Clock | None = None,
                 suffix: str = "") -> list[tuple[str, str]]:
    """Drive each scripted session through the gateway. Returns (session, lane) per request."""
    lanes = []
    for sid, repo, project, dial, caller, prompt, history, replies in sessions:
        sid = sid + suffix
        messages = [{"role": "system", "content": SYSTEM.format(root=f"/work/{repo}")}, *history,
                    {"role": "user", "content": prompt}]
        headers = {"x-cm-session": sid, "x-cm-project": project, "x-cm-dial": dial, "x-cm-client": caller}
        for reply in replies:
            model.next = reply
            r = client.post("/v1/chat/completions", json={"model": "auto", "messages": messages, "tools": TOOLS},
                            headers=headers)
            lanes.append((sid, r.headers["x-cm-lane"]))
            if r.status_code != 200:
                break
            msg = r.json()["choices"][0]["message"]
            messages.append(msg)
            for tc in msg.get("tool_calls") or []:
                args = json.loads(tc["function"]["arguments"])
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": run_tool(repo, tc["function"]["name"], args)})
        if clock:
            clock.gap((3, 14))
    return lanes


def gateway(out: Path, model: ScriptedModel, billing: str, local: bool) -> TestClient:
    config = Config(api_base=f"https://{META_HOST}/v1", api_key="demo-no-key", billing=billing,
                    local_api_base=f"http://{LOCAL_HOST}/v1" if local else "",
                    ledger_path=str(out / "ledger.db"), policy_path=str(out / "policy.db"))
    return TestClient(create_app(config, transport=httpx.MockTransport(model)))


def forbidden_values() -> list[str]:
    """Planted values that must never be in a Contributor request (FLOOR and CONFIDENTIAL canaries)."""
    values = [FAKE_KEY]
    for repo in ("slugkit", "billflow"):
        data = json.loads((MATERIALS / repo / "canaries.json").read_text(encoding="utf-8"))
        values += [c["value"] for c in data["canaries"] if c["label"] in ("FLOOR", "CONFIDENTIAL")]
    return values


def check(model: ScriptedModel, credits_from: int = 0) -> None:
    """No planted value reached Contributor, and on credits (calls from `credits_from` on) the Meta host
    received Contributor requests only."""
    for n, (host, body) in enumerate(model.calls):
        if host != META_HOST:
            continue
        if body["model"] != "muse-spark-1.3-contributor":
            if n >= credits_from:
                raise AssertionError(f"{body['model']} request reached Meta on credits")
            continue
        text = json.dumps(body, ensure_ascii=False)
        leaked = [v for v in forbidden_values() if v in text]
        if leaked:
            raise AssertionError(f"planted values reached Contributor: {leaked}")


def seed(out: Path, hours: float = 3.0, rng_seed: int = 7) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("ledger.db", "policy.db"):
        (out / name).unlink(missing_ok=True)
    rng = random.Random(rng_seed)
    clock = Clock(time.time() - hours * 3600, rng)
    model = ScriptedModel()
    lanes = []
    with ledger_clock(clock):
        lanes += run_sessions(gateway(out, model, "paid", local=False), model, PAID, clock)
        credits_from = len(model.calls)
        clock.gap((20, 30))
        client = gateway(out, model, "credits", local=False)
        lanes += run_sessions(client, model, CREDITS_HELD, clock)
        policy = client.app.state.policy
        for pattern, label in EARLIER_REVIEWS.items():
            item = next((p for p in policy.pending() if p["suggested_pattern"] == pattern), None)
            if item:
                policy.decide(item["id"], label)
            else:
                policy.set_rule(pattern, label)
        clock.gap((15, 25))
        lanes += run_sessions(gateway(out, model, "credits", local=True), model, CREDITS_LOCAL, clock)
    check(model, credits_from)
    return {"lanes": lanes, "pending": client.app.state.policy.pending()}


def replay(out: Path, local: bool = False) -> list[tuple[str, str]]:
    """Resend the sessions behind the pending review items, now, against the same files."""
    model = ScriptedModel()
    client = gateway(out, model, "credits", local=local)
    lanes = run_sessions(client, model, REPLAY, suffix=f"-{time.strftime('%H%M%S')}")
    check(model)
    return lanes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "dashboard" / "demo-data")
    ap.add_argument("--replay", action="store_true", help="resend the sessions behind the pending review items")
    ap.add_argument("--local", action="store_true", help="with --replay: a local model is configured")
    args = ap.parse_args()
    if args.replay:
        for sid, lane in replay(args.out, args.local):
            print(f"{lane:12} {sid}")
        return
    result = seed(args.out)
    counts: dict[str, int] = {}
    for _, lane in result["lanes"]:
        counts[lane] = counts.get(lane, 0) + 1
    print(f"wrote {args.out / 'ledger.db'} and {args.out / 'policy.db'}")
    print("requests per lane: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"pending review items: {len(result['pending'])}")
    for item in result["pending"]:
        print(f"  #{item['id']} {item['path']} -> {item['suggested_pattern']} ({item['hits']} held back)")


if __name__ == "__main__":
    main()
