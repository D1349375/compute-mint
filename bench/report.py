"""Write the results of a run: results.json, tasks.csv, learning_curve.csv, violations.csv, summary.md."""
import csv
import json
from collections import Counter
from pathlib import Path

from .armtypes import ARM_SPECS
from .metrics import learning_curve


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def usd(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}"


def mult(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}x"


def write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_tables(out_dir: Path, results: dict) -> None:
    rows, curve, viols = [], [], []
    for name, arm in results["arms"].items():
        for t in arm["tasks"]:
            rows.append([name, t["task_id"], t["index"], t["phase"], t["repo"], t["kind"], t["scope"],
                         "" if t["passed"] is None else int(t["passed"]), t["requests"],
                         t["lanes"]["contributor"], t["lanes"]["standard"], t["tokens"]["total"],
                         t["tokens"]["contributor"], f"{t['e']:.6f}", f"{t['cost']:.6f}", f"{t['counterfactual']:.6f}",
                         t.get("masked_spans", ""), t["violations"], t["origin_violations"], t.get("recalls", "")])
        curve += [list(r.values()) for r in learning_curve(arm)]
        viols += [[name, v["task_id"], v["request_seq"], v["canary"], v["kind"], v["label"], v["where"]]
                  for v in arm["violations"]]
    _write_csv(out_dir / "tasks.csv",
               ["arm", "task_id", "index", "phase", "repo", "kind", "scope", "passed", "requests", "contributor_requests",
                "standard_requests", "tokens_total", "tokens_contributor", "e", "cost_usd", "counterfactual_usd",
                "masked_spans", "violations", "origin_violations", "recalls"], rows)
    _write_csv(out_dir / "learning_curve.csv",
               ["arm", "task_index", "task_id", "phase", "e_task", "e_cumulative", "e_window", "passed", "violations",
                "rules_learned", "review_pending"], curve)
    _write_csv(out_dir / "violations.csv", ["arm", "task_id", "request_seq", "canary", "kind", "label", "where"], viols)


def _violation_sources(arm: dict) -> Counter:
    c: Counter = Counter()
    for v in arm["violations"]:
        where = v["where"].split(" (message")[0]
        where = where.split("(")[0] if where.startswith("tool:") else where
        c[where.strip()] += 1
    return c


def summary_markdown(results: dict) -> str:
    s = results["summaries"]
    o = results["options"]
    n_tasks = len(results["tasks"])
    early = sum(1 for t in results["tasks"] if t["phase"] == "early")
    lines = [
        "# Compute Mint bench: summary", "",
        f"{n_tasks} tasks ({early} early, {n_tasks - early} late), {sum(1 for t in results['tasks'] if t['repo'] == 'slugkit')} "
        f"on the public repo and {sum(1 for t in results['tasks'] if t['repo'] == 'billflow')} on the private one. "
        f"Upstream: **{o['upstream']}**. Reviewer budget: {o['reviews_per_task']} decisions per task, "
        f"error rate {o['reviewer_error_rate']}. Cache block: {o['cache_block_tokens']} tokens.", "",
        "## Headline", "",
        "| Arm | Acceptance | e | Paid | Counterfactual (all Standard) | Compute multiplier | Cache hit | Broker ratio | Masked spans | Canary violations |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, row in s.items():
        if row["executed"]:
            lines.append(
                f"| {row['title']} | {row['passed']}/{row['tasks']} ({pct(row['pass_rate'])}) | {pct(row['e'])} | "
                f"{usd(row['paid_usd'])} | {usd(row['baseline_standard_usd'])} | {mult(row['compute_multiplier'])} | "
                f"{pct(row['cache_hit_rate'])} | {row['broker_ratio']:.2f} | {row['masked_spans']} | "
                f"{row['violations']} ({row['tasks_with_violation']} tasks) |")
        else:
            lines.append(
                f"| {row['title']} | n/a (not executed) | {pct(row['e'])} compliant, {pct(row['e_unchecked'])} unchecked | "
                f"n/a | {usd(row['baseline_standard_usd'])} (hypothetical Contributor cost {usd(row['hypothetical_cost_usd'])}) | "
                f"n/a | n/a | n/a | 0 (not masked) | **{row['violations']}** ({row['tasks_with_violation']} tasks) |")
    lines += ["", "e = share of tokens served by Contributor (for the naive arm: share in Contributor requests that carried "
              "nothing forbidden). Counterfactual = the all-Standard arm's cost for the same tasks. Compute multiplier = "
              "counterfactual / paid. Canary violations count (Contributor request, canary) pairs; the target is 0.", ""]

    learners = [f"{row['title']}: {row['review_decisions']} review decisions, {row['rules_learned']} rules"
                for row in s.values() if row["executed"] and row.get("review_decisions")]
    if learners:
        lines += ["Learning effort: " + "; ".join(learners) + ".", ""]
    ceiling = s.get("oracle")
    lines += ["## Learning: early vs late tasks", "",
              "| Arm | e early | e late | Acceptance early | Acceptance late |" + (" Share of oracle e, early | late |" if ceiling else ""),
              "|---|---|---|---|---|" + ("---|---|" if ceiling else "")]
    for name, row in s.items():
        extra = ""
        if ceiling:
            def share(phase: str) -> str:
                a, b = row.get(f"e_{phase}"), ceiling.get(f"e_{phase}")
                return pct(a / b) if a is not None and b else "n/a"
            extra = f" {share('early')} | {share('late')} |" if name not in ("standard", "naive") else " | |"
        lines.append(f"| {row['title']} | {pct(row['e_early'])} | {pct(row['e_late'])} | {pct(row['pass_rate_early'])} | "
                     f"{pct(row['pass_rate_late'])} |" + extra)
    lines += ["", "The task mix differs between the two phases, so compare an arm with the oracle ceiling (every path rule known "
              "from the start) rather than early with late. The per-task series is in `learning_curve.csv` (x axis: task order).", ""]

    lines += ["## e by repository", "", "| Arm | public repo (slugkit) | private repo (billflow) |", "|---|---|---|"]
    for name, row in s.items():
        lines.append(f"| {row['title']} | {pct(row['e_by_repo'].get('slugkit'))} | {pct(row['e_by_repo'].get('billflow'))} |")
    lines.append("")

    if "naive_variants" in results:
        lines += ["## Naive switch: when is the model flipped?", "",
                  "| Switch point | e (compliant) | e (unchecked) | Violations | Violating requests | Tasks affected | Origin violations |",
                  "|---|---|---|---|---|---|---|"]
        for policy, v in results["naive_variants"].items():
            lines.append(f"| {policy} | {pct(v['e_compliant'])} | {pct(v['e_unchecked'])} | {v['violations']} | "
                         f"{v['violating_requests']} | {v['tasks_with_violation']} | {v['origin_violations']} |")
        lines += ["", "start = whole task on Contributor; mid = after half of the requests (used in the headline); "
                  "late = only the last request.", ""]

    leaking = {n: a for n, a in results["arms"].items() if a["violations"] and ARM_SPECS[n].executed}
    if leaking:
        lines += ["## Where the canaries got through (executed arms)", "",
                  "| Arm | Violations (request x canary) | Incidents (task x canary) | Requests | Tasks | Source in the request |",
                  "|---|---|---|---|---|---|"]
        for name, arm in leaking.items():
            sm = s[name]
            sources = ", ".join(f"{src} ({n})" for src, n in sorted(_violation_sources(arm).items()))
            lines.append(f"| {name} | {sm['violations']} | {sm['violation_incidents']} | {sm['violating_requests']} | "
                         f"{sm['tasks_with_violation']} | {sources} |")
        lines += ["", "Details per violation (task, request, canary, source): `violations.csv`.", ""]
    else:
        lines += ["## Canary check", "", "No canary reached a Contributor request in any executed arm.", ""]

    failed = {n: [t["task_id"] for t in a["tasks"] if t["passed"] is False] for n, a in results["arms"].items()}
    failed = {n: ids for n, ids in failed.items() if ids}
    if failed:
        lines += ["## Tasks that failed acceptance", ""]
        lines += [f"- {n}: {', '.join(ids)}" for n, ids in failed.items()]
        lines.append("")
    return "\n".join(lines)
