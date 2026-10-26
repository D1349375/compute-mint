"""Aggregate per-task records into the headline metrics of an arm.

Definitions (all token counts are the upstream's `usage`, or the estimator's in mock mode):

e                      share of all tokens (prompt + completion) in requests served by Contributor.
                       For the naive arm: share in Contributor requests that carried nothing forbidden.
pass_rate              tasks whose deterministic acceptance passed / tasks.
paid_usd               sum of the ledger's cost (official prices, cache-aware).
baseline_standard_usd  what the same tasks cost in the all-Standard arm (the counterfactual that
                       includes the Context Broker's effect; the ledger's own counterfactual only
                       re-prices the tokens that were actually sent).
compute_multiplier     baseline_standard_usd / paid_usd.
ledger_multiplier      the ledger's counterfactual / paid_usd.
cache_hit_rate         cached prompt tokens / prompt tokens.
broker_ratio           characters sent / characters before the Context Broker (1.0 = untouched).
violations             (Contributor request, canary) pairs; the target is 0.
violation_incidents    distinct (task, canary) pairs: how many different secrets left in each task,
                       however many requests carried them.
"""


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def _share(tasks: list[dict], key: str = "contributor") -> float | None:
    return _ratio(sum(t["tokens"][key] for t in tasks), sum(t["tokens"]["total"] for t in tasks))


def _pass_rate(tasks: list[dict]) -> float | None:
    done = [t for t in tasks if t["passed"] is not None]
    return _ratio(sum(1 for t in done if t["passed"]), len(done)) if done else None


def summarize(arm: dict, baseline_cost: float | None, executed: bool = True) -> dict:
    tasks = arm["tasks"]
    early = [t for t in tasks if t["phase"] == "early"]
    late = [t for t in tasks if t["phase"] == "late"]
    spent = sum(t["cost"] for t in tasks)
    prompt = sum(t["tokens"].get("prompt", 0) for t in tasks)
    cached = sum(t["tokens"].get("cached", 0) for t in tasks)
    chars_in = sum(t.get("broker", {}).get("chars_in", 0) for t in tasks)
    chars_out = sum(t.get("broker", {}).get("chars_out", 0) for t in tasks)
    viol = arm["violations"]
    out = {
        "arm": arm["arm"], "title": arm["title"], "executed": executed,
        "tasks": len(tasks),
        "passed": sum(1 for t in tasks if t["passed"]) if executed else None,
        "pass_rate": _pass_rate(tasks), "pass_rate_early": _pass_rate(early), "pass_rate_late": _pass_rate(late),
        "requests": sum(t["requests"] for t in tasks),
        "tokens_total": sum(t["tokens"]["total"] for t in tasks),
        "e": _share(tasks), "e_early": _share(early), "e_late": _share(late),
        "e_requests": _ratio(sum(t["lanes"]["contributor"] for t in tasks), sum(t["requests"] for t in tasks)),
        "e_by_repo": {repo: _share([t for t in tasks if t["repo"] == repo]) for repo in sorted({t["repo"] for t in tasks})},
        "violations": sum(t["violations"] for t in tasks) if not viol else len(viol),
        "leaked_canaries": len({v["canary"] for v in viol}) if viol else
                           len({c for t in tasks for c in t.get("leaked_canaries", [])}),
        "violating_requests": sum(t.get("violating_requests", 0) for t in tasks) if not executed else
                              len({(v["task_id"], v["request_seq"]) for v in viol}),
        "violation_incidents": len({(v["task_id"], v["canary"]) for v in viol}) if executed else
                               sum(len(t.get("leaked_canaries", [])) for t in tasks),
        "tasks_with_violation": sum(1 for t in tasks if t["violations"] or t["origin_violations"]),
        "origin_violations": arm["origin_violations"],
    }
    if executed:
        out.update({
            "tokens_prompt": prompt, "tokens_cached": cached,
            "paid_usd": spent, "ledger_counterfactual_usd": sum(t["counterfactual"] for t in tasks),
            "baseline_standard_usd": baseline_cost,
            "compute_multiplier": _ratio(baseline_cost, spent) if baseline_cost is not None else None,
            "ledger_multiplier": _ratio(sum(t["counterfactual"] for t in tasks), spent),
            "cache_hit_rate": _ratio(cached, prompt),
            "broker_ratio": _ratio(chars_out, chars_in),
            "masked_spans": sum(t["masked_spans"] for t in tasks),
            "recalls": sum(t["recalls"] for t in tasks),
            "review_decisions": len(arm["reviewer_decisions"]), "rules_learned": len(arm["rules"]),
        })
    else:
        out.update({
            "e_unchecked": _share(tasks, "contributor_unchecked"),
            "hypothetical_cost_usd": spent,
            "baseline_standard_usd": baseline_cost,
            "note": "simulated from recorded histories; nothing was sent anywhere",
        })
    return out


def learning_curve(arm: dict, window: int = 5) -> list[dict]:
    """Per task: e of the task, cumulative e, e over the last `window` tasks, plus the learned-rule count."""
    rows, tot, con = [], 0, 0
    recent: list[tuple[int, int]] = []
    for t in arm["tasks"]:
        tot += t["tokens"]["total"]
        con += t["tokens"]["contributor"]
        recent.append((t["tokens"]["contributor"], t["tokens"]["total"]))
        recent = recent[-window:]
        w_tot = sum(b for _a, b in recent)
        rows.append({
            "arm": arm["arm"], "task_index": t["index"], "task_id": t["task_id"], "phase": t["phase"],
            "e_task": round(t["e"], 6), "e_cumulative": round(con / tot, 6) if tot else 0.0,
            "e_window": round(sum(a for a, _b in recent) / w_tot, 6) if w_tot else 0.0,
            "passed": "" if t["passed"] is None else int(t["passed"]),
            "violations": t["violations"],
            "rules_learned": t.get("review", {}).get("rules", ""),
            "review_pending": t.get("review", {}).get("pending", ""),
        })
    return rows
