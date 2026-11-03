"""Put several real-upstream runs side by side: pass rate and cost per arm, and per task across the runs.

    python -m bench.realsummary bench/results/real-r1 bench/results/real-r2 bench/results/real-r3

Costs are computed from the `usage` the API returned and the Meta price table (what the gateway's ledger
holds), not read from an invoice. Only runs made with `--upstream meta` make sense here.
"""
import json
import sys
from pathlib import Path


def load(dirs: list[str]) -> list[dict]:
    return [json.loads((Path(d) / "results.json").read_text(encoding="utf-8")) for d in dirs]


def arm_totals(runs: list[dict], arm: str) -> dict:
    tasks = [t for r in runs for t in r["arms"][arm]["tasks"]]
    n = len(tasks)
    prompt = sum(t["tokens"]["prompt"] for t in tasks)
    return {"tasks": n, "passed": sum(t["passed"] for t in tasks), "errors": sum(1 for t in tasks if t.get("error")),
            "unfinished": sum(1 for t in tasks if not t["finished"]), "requests": sum(t["requests"] for t in tasks),
            "prompt": prompt, "cached": sum(t["tokens"]["cached"] for t in tasks),
            "completion": sum(t["tokens"]["completion"] for t in tasks),
            "contributor": sum(t["tokens"]["contributor"] for t in tasks),
            "total": sum(t["tokens"]["total"] for t in tasks),
            "cost": sum(t["cost"] for t in tasks), "counterfactual": sum(t["counterfactual"] for t in tasks),
            "canary": sum(t["violations"] for t in tasks), "origin": sum(t["origin_violations"] for t in tasks)}


def render(runs: list[dict]) -> str:
    arms = list(runs[0]["arms"])
    out = [f"{len(runs)} runs, {len(runs[0]['tasks'])} tasks each; real upstream, computed spend "
           f"${sum(r['real_upstream']['computed_spend_usd'] for r in runs):.4f} in {sum(r['real_upstream']['requests'] for r in runs)} requests.\n",
           "| Arm | Passed | Pass rate | Requests | Prompt tok | Cached | Completion tok | e | Cost | Counterfactual | Canary |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    totals = {a: arm_totals(runs, a) for a in arms}
    for a, t in totals.items():
        out.append(f"| {runs[0]['arms'][a]['title']} | {t['passed']}/{t['tasks']} | {100 * t['passed'] / t['tasks']:.1f}% | {t['requests']} "
                   f"| {t['prompt']} | {t['cached']} | {t['completion']} | {100 * t['contributor'] / t['total']:.1f}% "
                   f"| ${t['cost']:.4f} | ${t['counterfactual']:.4f} | {t['canary']} |")
    if "standard" in totals:
        base = totals["standard"]
        out.append("")
        for a, t in totals.items():
            if a != "standard" and t["cost"] > 0:
                out.append(f"- {a}: ${t['cost']:.4f} against ${base['cost']:.4f} for all Standard = **{base['cost'] / t['cost']:.1f}x** cheaper "
                           f"(per task ${t['cost'] / t['tasks']:.4f} vs ${base['cost'] / base['tasks']:.4f}); "
                           f"completion tokens per task {t['completion'] / t['tasks']:.0f} vs {base['completion'] / base['tasks']:.0f}.")
    out += ["", "Per task (passes over runs):", "", "| Task | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for i, task in enumerate(runs[0]["tasks"]):
        cells = []
        for a in arms:
            recs = [r["arms"][a]["tasks"][i] for r in runs]
            cells.append(f"{sum(x['passed'] for x in recs)}/{len(recs)}")
        out.append(f"| {task['id']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    print(render(load(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
