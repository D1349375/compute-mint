"""The naive arm: switch the model to Contributor in the middle of a session, carrying the full history.

THIS ARM IS ANALYSIS ONLY. It never builds a gateway, never touches an upstream and cannot send
anything anywhere, even when the other arms later run against a real API: it only reads the
histories the Standard arm's agent produced and asks, request by request, "if the full raw
history had been sent to Contributor from here on, what would have left, and how much of it
should not have?". `analyze_naive` takes no client, transport or URL.

For a task with R requests and a switch point s (requests 0..s-1 stay on Standard, s..R-1 go to
Contributor with the raw, unmasked, unfiltered history):

- start: s = 0           the whole task on Contributor
- mid:   s = max(1, R//2) the user flips the model half-way (the default, "mid-session")
- late:  s = R - 1       only the last request

A Contributor request is *compliant* if it carries no canary that is not contributable under the
task's dial and no text written by another vendor's model. `e` for this arm is the share of all
tokens that sat in compliant Contributor requests (the analogue of the 8.8% in the project's
own session analysis); `e_unchecked` is the share that a naive user would believe they moved.
"""
import json

from compute_mint.pricing import Usage, cost

from .armtypes import ARM_SPECS, CONTRIBUTOR_MODEL, DIALS, STANDARD_MODEL, ArmRun
from .cachesim import PrefixCache
from .canary import origin_violations_in, scan_request
from .repos import load_repo
from .taskmodel import IndexedTask
from .tools import TOOL_SPECS

POLICIES = ("start", "mid", "late")


def switch_point(policy: str, requests: int) -> int:
    if policy == "start":
        return 0
    if policy == "late":
        return max(0, requests - 1)
    if policy == "mid":
        return max(1, requests // 2) if requests > 1 else 0
    raise ValueError(f"unknown naive switch policy {policy!r}")


def _task_record(it: IndexedTask, snapshots: list[list[dict]], completions: list[int], policy: str,
                 cache_block_tokens: int) -> dict:
    task = it.task
    repo = load_repo(task.repo)
    dial = DIALS[task.headers(repo.headers)["x-cm-dial"]]
    foreign = [m["content"] for m in task.seed if m["role"] == "assistant"]
    s = switch_point(policy, len(snapshots))
    cache = PrefixCache(cache_block_tokens)
    tools_seg = json.dumps(TOOL_SPECS, sort_keys=True, ensure_ascii=False)

    total = contributor = compliant = 0
    spent = counterfactual = 0.0
    viol_pairs = origin = bad_requests = 0
    leaked: set[str] = set()
    for i, messages in enumerate(snapshots):
        model = CONTRIBUTOR_MODEL if i >= s else STANDARD_MODEL
        segments = [tools_seg] + [json.dumps(m, sort_keys=True, ensure_ascii=False) for m in messages]
        prompt, cached = cache.lookup_and_insert(model, segments)
        usage = Usage(prompt, cached, completions[i])
        tokens = prompt + completions[i]
        total += tokens
        spent += cost(model, usage)
        counterfactual += cost(STANDARD_MODEL, usage)
        if i < s:
            continue
        contributor += tokens
        body = {"model": model, "messages": messages, "tools": TOOL_SPECS}
        found = scan_request(body, repo.canaries, dial, task_id=task.id, seq=i)
        n_origin = origin_violations_in(body, foreign)
        viol_pairs += len(found)
        origin += n_origin
        leaked |= {v.canary_id for v in found}
        if found or n_origin:
            bad_requests += 1
        else:
            compliant += tokens
    return {
        "task_id": task.id, "index": it.index, "phase": it.phase, "repo": task.repo, "kind": task.kind,
        "scope": task.scope, "tags": list(task.tags), "passed": None, "requests": len(snapshots),
        "switch_at": s, "lanes": {"contributor": len(snapshots) - s, "standard": s},
        "tokens": {"total": total, "contributor": compliant, "contributor_unchecked": contributor},
        "e": compliant / total if total else 0.0,
        "cost": spent, "counterfactual": counterfactual,
        "violations": viol_pairs, "origin_violations": origin, "violating_requests": bad_requests,
        "leaked_canaries": sorted(leaked),
    }


def analyze_naive(tasks: tuple[IndexedTask, ...], standard: ArmRun, policy: str = "mid",
                  cache_block_tokens: int = 64) -> ArmRun:
    """Simulate the naive switch over the histories recorded by the Standard arm. Nothing is sent."""
    out = ArmRun(ARM_SPECS["naive"])
    by_id = {t["task_id"]: t for t in standard.tasks}
    for it in tasks:
        completions = [r["completion"] for r in by_id[it.task.id]["per_request"]]
        out.tasks.append(_task_record(it, standard.snapshots[it.task.id], completions, policy, cache_block_tokens))
    out.origin_violations = sum(t["origin_violations"] for t in out.tasks)
    return out


def variants(tasks: tuple[IndexedTask, ...], standard: ArmRun, cache_block_tokens: int = 64) -> dict[str, dict]:
    """Headline numbers of every switch policy (for the sensitivity table)."""
    res = {}
    for policy in POLICIES:
        run = analyze_naive(tasks, standard, policy, cache_block_tokens)
        total = sum(t["tokens"]["total"] for t in run.tasks)
        res[policy] = {
            "e_compliant": sum(t["tokens"]["contributor"] for t in run.tasks) / total if total else 0.0,
            "e_unchecked": sum(t["tokens"]["contributor_unchecked"] for t in run.tasks) / total if total else 0.0,
            "violations": sum(t["violations"] for t in run.tasks),
            "origin_violations": sum(t["origin_violations"] for t in run.tasks),
            "violating_requests": sum(t["violating_requests"] for t in run.tasks),
            "tasks_with_violation": sum(1 for t in run.tasks if t["violations"] or t["origin_violations"]),
            "hypothetical_cost": sum(t["cost"] for t in run.tasks),
        }
    return res
