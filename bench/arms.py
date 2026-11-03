"""The experimental arms and the runner that executes one arm over the task set.

standard      everything on Standard (no Mint): the cost baseline
naive         full history switched to Contributor mid-session: SIMULATED ONLY (see naive.py)
mint          lanes + masking + origin (routing by label, no learning, no Context Broker)
mint_broker   mint + Context Broker
mint_learn    mint_broker + learned path rules from a simulated reviewer
oracle        mint_broker with every path rule preloaded from the truth (ceiling for learning; extra arm)
mint_strict   mint_learn with a what-if shim: tool output that names no file is treated as unreviewed (extra arm)

Each executed arm gets its own gateway app (so its own ledger, policy and sessions), its own mock
upstream and prompt cache, and sees the same tasks in the same order.
"""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from compute_mint.app import Config, SessionState, create_app
from compute_mint.broker import Broker, BrokerConfig
from compute_mint.labels import Label

from .acceptance import evaluate
from .agent import AgentRun, run_agent
from .armtypes import ALL_ARMS, ARM_SPECS, CONTRIBUTOR_MODEL, DIALS, STANDARD_MODEL, ArmRun, ArmSpec, RunOptions
from .canary import origin_violations_in, scan_request
from .repos import Repo, load_repo, repo_names, write_tree
from .reviewer import Reviewer, truth_paths
from .shims import strict_tool_outputs
from .taskmodel import IndexedTask
from .tools import Workspace, mount_for
from .upstream import RecordingTransport, make_upstream

class GatewayChat:
    """chat(messages, tools) against the gateway; returns (assistant message, meta)."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client, self.headers = client, headers

    def __call__(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        r = self.client.post("/v1/chat/completions", headers=self.headers,
                             json={"model": "bench-agent", "messages": messages, "tools": tools})
        if r.status_code != 200:
            raise RuntimeError(f"gateway returned {r.status_code}: {r.text[:300]}")
        data = r.json()
        meta = {"lane": r.headers["x-cm-lane"], "masked_spans": int(r.headers["x-cm-masked-spans"]),
                "usage": data.get("usage") or {}}
        return data["choices"][0]["message"], meta


def _ledger_rows(app, session: str) -> list[dict]:
    cols = ["lane", "prompt_tokens", "cached_tokens", "completion_tokens", "cost", "counterfactual", "masked_spans",
            "chars_in", "chars_out", "reason"]
    cur = app.state.ledger.db.execute(f"SELECT {', '.join(cols)} FROM requests WHERE session = ? ORDER BY id", (session,))
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _recalls(snapshot: list[dict]) -> int:
    return sum(1 for m in snapshot if m.get("role") == "assistant"
               for c in m.get("tool_calls") or [] if str(c.get("id", "")).startswith("recall_"))


def task_record(it: IndexedTask, arm: str, run: AgentRun, accept: dict, rows: list[dict]) -> dict:
    prompt = sum(r["prompt_tokens"] for r in rows)
    cached = sum(r["cached_tokens"] for r in rows)
    completion = sum(r["completion_tokens"] for r in rows)
    total = prompt + completion
    contributor = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows if r["lane"] == "contributor")
    t = it.task
    return {
        "task_id": t.id, "index": it.index, "phase": it.phase, "repo": t.repo, "kind": t.kind, "scope": t.scope,
        "tags": list(t.tags), "passed": accept["passed"], "checks": accept["checks"], "finished": run.finished,
        "requests": len(rows),
        "lanes": {"contributor": sum(r["lane"] == "contributor" for r in rows),
                  "standard": sum(r["lane"] == "standard" for r in rows)},
        "tokens": {"prompt": prompt, "cached": cached, "completion": completion, "total": total, "contributor": contributor},
        "e": contributor / total if total else 0.0,
        "cost": sum(r["cost"] for r in rows), "counterfactual": sum(r["counterfactual"] for r in rows),
        "masked_spans": sum(r["masked_spans"] for r in rows),
        "broker": {"chars_in": sum(r["chars_in"] for r in rows), "chars_out": sum(r["chars_out"] for r in rows)},
        "recalls": _recalls(run.snapshots[-1]) if run.snapshots else 0,
        "per_request": [{"lane": r["lane"], "prompt": r["prompt_tokens"], "cached": r["cached_tokens"],
                         "completion": r["completion_tokens"], "masked": r["masked_spans"], "reason": r["reason"]}
                        for r in rows],
        "violations": 0, "origin_violations": 0,
    }


def run_arm(spec: ArmSpec, tasks: tuple[IndexedTask, ...], options: RunOptions) -> ArmRun:
    if not spec.executed:
        raise ValueError(f"{spec.name} is analysed, not executed")
    real = options.upstream == "meta"
    upstream = make_upstream(options.upstream, **({"budget_usd": options.budget_usd} if real
                                                  else {"cache_block_tokens": options.cache_block_tokens}))
    recorder = RecordingTransport(upstream.transport())
    # Routing uses `paid` in every mode: it only decides that what is not contributable goes to the Standard lane.
    # With the real API this is acceptable because every byte of bench data is invented.
    config = Config(api_base=upstream.api_base if real else "https://mock.invalid/v1",
                    api_key=upstream.api_key if real else "mock-key-not-a-real-key",
                    contributor_model=CONTRIBUTOR_MODEL, standard_model=STANDARD_MODEL,
                    ledger_path=":memory:", policy_path=":memory:", billing="paid",
                    output_paths=spec.output_paths, fingerprints=spec.fingerprints,
                    fingerprint_threshold=spec.fingerprint_threshold)
    app = create_app(config, transport=recorder)
    if spec.strict_tools:
        strict_tool_outputs(app.state.policy)
    client = TestClient(app)
    if real:
        client.__enter__()   # one event loop for the whole arm: the real HTTP connections are reused between requests
    repos: dict[str, Repo] = {n: load_repo(n) for n in repo_names()}
    truth = truth_paths(repos, {n: [it.task.id for it in tasks if it.task.repo == n] for n in repos})
    if spec.learning == "oracle" or spec.public_repo:   # a rule per file from the truth; the strictest label wins over the blanket rule below
        for path, label in truth.items():
            app.state.policy.set_rule(path, label)
    if spec.public_repo:
        for name, repo in repos.items():
            if repo.headers["project"] == "public":
                app.state.policy.set_rule(f"{mount_for(name)}/*", Label.PUBLIC)
    reviewer = Reviewer(truth, budget=options.reviews_per_task, error_rate=options.reviewer_error_rate,
                        seed=options.seed) if spec.learning == "reviewer" else None

    out = ArmRun(spec)
    first_request: dict[str, int] = {}
    for it in tasks:
        task = it.task
        repo = repos[task.repo]
        session = f"{spec.name}-{task.id}"
        headers = {"x-cm-session": session, "x-cm-root": mount_for(task.repo), **task.headers(repo.headers)}
        if spec.all_standard:
            headers["x-cm-project"] = "confidential"
        broker = Broker() if spec.broker else Broker(BrokerConfig(compact_over_chars=10 ** 12))
        app.state.sessions[session] = SessionState(broker=broker)

        upstream.begin_task(task)
        recorder.current_task = task.id
        first_request[task.id] = len(recorder.requests)
        with tempfile.TemporaryDirectory(prefix="bench-") as tmp:
            root = Path(tmp)
            write_tree(repo.files, root)
            ws = Workspace(root, mount_for(task.repo))
            error = ""
            try:
                run = run_agent(task, GatewayChat(client, headers), ws)
            except Exception as e:
                if not real or upstream.over_budget:
                    raise
                run, error = AgentRun(), f"{type(e).__name__}: {str(e)[:300]}"   # a real call failed: the task counts as not passed
            accept = evaluate(task, root, run.final_text)
        rec = task_record(it, spec.name, run, accept, _ledger_rows(app, session))
        if error:
            rec["error"] = error
        if options.progress_path:
            import json
            with open(options.progress_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"arm": spec.name, **rec}, ensure_ascii=False) + "\n")
        out.snapshots[task.id] = run.snapshots
        if reviewer is not None:
            decided = reviewer.review(client, task.id)
            queue = client.get("/v1/review").json()
            rec["review"] = {"decided": decided, "pending": len(queue["pending"]), "rules": len(queue["rules"])}
        out.tasks.append(rec)

    _scan(out, recorder, tasks, repos, first_request)
    review = client.get("/v1/review").json()
    out.rules = sorted(review["rules"], key=lambda r: (r["pattern"], r["label"]))
    if reviewer is not None:
        out.reviewer_decisions = reviewer.decisions
    out.sent_checks = _cross_check_ledger(app, recorder)
    if real:
        client.__exit__(None, None, None)
    return out


def _scan(out: ArmRun, recorder: RecordingTransport, tasks, repos, first_request: dict[str, int]) -> None:
    by_id = {it.task.id: (it, rec) for it, rec in zip(tasks, out.tasks)}
    for req in recorder.requests:
        if req.model != CONTRIBUTOR_MODEL:
            continue
        it, rec = by_id[req.task_id]
        repo = repos[it.task.repo]
        dial = DIALS[it.task.headers(repo.headers)["x-cm-dial"]]
        seq = req.seq - first_request[req.task_id]
        found = scan_request(req.body, repo.canaries, dial, task_id=req.task_id, seq=seq)
        rec["violations"] += len(found)
        out.violations += [v.as_dict() for v in found]
        foreign = [m["content"] for m in it.task.seed if m["role"] == "assistant"]
        n = origin_violations_in(req.body, foreign)
        rec["origin_violations"] += n
        out.origin_violations += n


def _cross_check_ledger(app, recorder: RecordingTransport) -> dict:
    """The gateway's own record of what it sent to Contributor must equal what the recorder saw."""
    import json
    cur = app.state.ledger.db.execute("SELECT sent_payload FROM requests WHERE lane = 'contributor' ORDER BY id")
    ledger_payloads = [row[0] for row in cur.fetchall()]
    seen = [json.dumps(r.body["messages"], ensure_ascii=False, sort_keys=True)
            for r in recorder.requests if r.model == CONTRIBUTOR_MODEL]
    return {"contributor_requests_ledger": len(ledger_payloads), "contributor_requests_seen": len(seen),
            "payloads_identical": ledger_payloads == seen}
