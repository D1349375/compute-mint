"""Run the bench.

    python -m bench.run --arms all --upstream mock
    python -m bench.run --arms standard,mint --tasks T01,T14
    python -m bench.run --arms all,oracle --out bench/sample_results --run-id sample

    python -m bench.run --arms standard,oracle --tasks T07,T09 --upstream meta --budget 2

`--upstream meta` sends the (invented) bench data to the real Meta Model API: the key comes from META_API_KEY
(`.env` at the repository root is read, nothing is printed) and `--budget` caps the computed spend in USD.
The `naive` arm is never executed against any upstream (it is analysed from the Standard arm's recorded histories).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import BENCH_DIR
from .armtypes import ALL_ARMS, ARM_SPECS, RunOptions
from .metrics import summarize
from .naive import analyze_naive, variants
from .report import summary_markdown, write_json, write_tables
from .taskset import select


def parse_arms(text: str) -> list[str]:
    names: list[str] = []
    for part in (p.strip() for p in text.split(",") if p.strip()):
        for name in (ALL_ARMS if part == "all" else [part]):
            if name not in ARM_SPECS:
                raise SystemExit(f"unknown arm {name!r}; choose from {', '.join(ARM_SPECS)} or 'all'")
            if name not in names:
                names.append(name)
    return names


def run_bench(arms: list[str], options: RunOptions, task_ids: list[str] | None = None, limit: int | None = None) -> dict:
    from .arms import run_arm   # imported late: the naive arm and the CLI help must not need the gateway

    tasks = select(task_ids, limit)
    if not tasks:
        raise SystemExit("no tasks selected")
    order = [n for n in ARM_SPECS if n in arms or n == "standard"]   # the Standard arm is always the reference
    runs = {}
    for name in order:
        spec = ARM_SPECS[name]
        if spec.executed:
            runs[name] = run_arm(spec, tasks, options)
    if "naive" in order:
        runs["naive"] = analyze_naive(tasks, runs["standard"], options.naive_switch, options.cache_block_tokens)

    baseline = sum(t["cost"] for t in runs["standard"].tasks) if "standard" in runs else None
    arm_docs = {n: runs[n].to_dict() for n in order}
    summaries = {n: summarize(arm_docs[n], baseline, ARM_SPECS[n].executed) for n in order}
    results = {
        "options": {"upstream": options.upstream, "cache_block_tokens": options.cache_block_tokens,
                    "reviews_per_task": options.reviews_per_task, "reviewer_error_rate": options.reviewer_error_rate,
                    "seed": options.seed, "naive_switch": options.naive_switch},
        "tasks": [{"id": it.task.id, "index": it.index, "phase": it.phase, "repo": it.task.repo, "kind": it.task.kind,
                   "scope": it.task.scope, "lang": it.task.lang, "tags": list(it.task.tags)} for it in tasks],
        "summaries": summaries,
        "arms": arm_docs,
        "integrity": {n: runs[n].sent_checks for n in order if ARM_SPECS[n].executed},
    }
    if options.upstream == "meta":
        from .upstream import MetaUpstream
        results["options"]["budget_usd"] = options.budget_usd
        results["real_upstream"] = {"computed_spend_usd": round(MetaUpstream.spent_usd, 6), "requests": MetaUpstream.requests}
    if "naive" in order:
        results["naive_variants"] = variants(tasks, runs["standard"], options.cache_block_tokens)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bench.run", description=__doc__.split("\n")[0])
    p.add_argument("--arms", default="all", help="comma list of: " + ", ".join(ARM_SPECS) + " (all = the five of the spec)")
    p.add_argument("--upstream", default="mock", choices=["mock", "meta"], help="meta = the real Meta Model API (needs META_API_KEY)")
    p.add_argument("--budget", type=float, default=0.0, help="--upstream meta: stop once the computed spend reaches this many USD")
    p.add_argument("--tasks", default="", help="comma list of task ids or numbers (T01,T14); default all")
    p.add_argument("--limit", type=int, default=0, help="only the first N tasks (of the selection)")
    p.add_argument("--out", default=str(BENCH_DIR / "results"), help="output base directory")
    p.add_argument("--run-id", default="", help="directory name under --out (default: UTC timestamp)")
    p.add_argument("--reviews-per-task", type=int, default=2, help="decisions the simulated reviewer makes after each task")
    p.add_argument("--reviewer-error-rate", type=float, default=0.0, help="share of review answers replaced by 'public'")
    p.add_argument("--cache-block", type=int, default=64, help="prompt-cache granularity in tokens (mock upstream)")
    p.add_argument("--naive-switch", default="mid", choices=["start", "mid", "late"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--compare", default="", help="results.json or summary.json of an earlier run: adds a before/after table")
    args = p.parse_args(argv)

    if args.upstream == "meta":
        from compute_mint.envfile import load_env_file
        load_env_file(BENCH_DIR.parent / ".env")
        if not os.environ.get("META_API_KEY"):
            print("--upstream meta needs META_API_KEY (set it or put it in .env at the repository root).", file=sys.stderr)
            return 2
        if args.budget <= 0:
            print("--upstream meta needs --budget (USD): a cap on the computed spend.", file=sys.stderr)
            return 2
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / run_id
    options = RunOptions(upstream=args.upstream, cache_block_tokens=args.cache_block, reviews_per_task=args.reviews_per_task,
                         reviewer_error_rate=args.reviewer_error_rate, seed=args.seed, naive_switch=args.naive_switch,
                         budget_usd=args.budget, progress_path=str(out_dir / "progress.jsonl") if args.upstream == "meta" else "")
    if options.progress_path:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = run_bench(parse_arms(args.arms), options, [t for t in args.tasks.split(",") if t] or None, args.limit or None)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "results.json", results)
    write_tables(out_dir, results)
    before = json.loads(Path(args.compare).read_text(encoding="utf-8")) if args.compare else None
    (out_dir / "summary.md").write_text(summary_markdown(results, before), encoding="utf-8", newline="\n")
    write_json(out_dir / "meta.json", {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "python": sys.version.split()[0], "command": " ".join(sys.argv[1:] if argv is None else argv)})
    print((out_dir / "summary.md").read_text(encoding="utf-8"))
    print(f"results written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
