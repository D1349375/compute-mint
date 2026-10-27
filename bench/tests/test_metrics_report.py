import csv
import io

import pytest

from bench.metrics import learning_curve, summarize
from bench.report import pct, summary_markdown, write_tables


def task(i, phase, total, contributor, cost=0.01, cf=0.02, passed=True, repo="slugkit", violations=0, review=None):
    t = {"task_id": f"T{i:02d}", "index": i, "phase": phase, "repo": repo, "kind": "bug", "scope": "repo", "passed": passed,
         "requests": 4, "lanes": {"contributor": 2 if contributor else 0, "standard": 2 if contributor else 4},
         "tokens": {"prompt": total - 100, "cached": (total - 100) // 2, "completion": 100, "total": total,
                    "contributor": contributor},
         "e": contributor / total, "cost": cost, "counterfactual": cf, "masked_spans": 1,
         "broker": {"chars_in": 1000, "chars_out": 900}, "recalls": 0, "violations": violations, "origin_violations": 0}
    if review:
        t["review"] = review
    return t


def arm(tasks, violations=()):
    return {"arm": "mint", "title": "3. Mint", "tasks": tasks, "violations": list(violations), "origin_violations": 0,
            "reviewer_decisions": [], "rules": []}


def test_summary_numbers():
    tasks = [task(0, "early", 1000, 0), task(1, "early", 1000, 500), task(2, "late", 2000, 1500, passed=False, repo="billflow")]
    s = summarize(arm(tasks), baseline_cost=0.06)
    assert s["e"] == pytest.approx(2000 / 4000)
    assert s["e_early"] == pytest.approx(0.25) and s["e_late"] == pytest.approx(0.75)
    assert s["pass_rate"] == pytest.approx(2 / 3) and s["pass_rate_early"] == 1.0 and s["pass_rate_late"] == 0.0
    assert s["paid_usd"] == pytest.approx(0.03) and s["compute_multiplier"] == pytest.approx(2.0)
    assert s["ledger_multiplier"] == pytest.approx(2.0)
    assert s["broker_ratio"] == pytest.approx(0.9)
    assert s["cache_hit_rate"] == pytest.approx(sum((t["tokens"]["prompt"]) // 2 for t in tasks) / sum(t["tokens"]["prompt"] for t in tasks))
    assert s["e_by_repo"] == {"billflow": pytest.approx(0.75), "slugkit": pytest.approx(0.25)}
    assert s["masked_spans"] == 3 and s["violations"] == 0


def test_violation_counts_distinguish_pairs_requests_and_incidents():
    v = lambda task_id, seq, canary: {"task_id": task_id, "request_seq": seq, "canary": canary, "kind": "k", "label": "FLOOR", "where": "w"}
    viols = [v("T01", 1, "a"), v("T01", 1, "b"), v("T01", 2, "a"), v("T02", 0, "a")]
    tasks = [task(0, "early", 1000, 500, violations=3), task(1, "early", 1000, 500, violations=1)]
    s = summarize(arm(tasks, viols), baseline_cost=None)
    assert s["violations"] == 4 and s["violating_requests"] == 3 and s["violation_incidents"] == 3
    assert s["leaked_canaries"] == 2 and s["compute_multiplier"] is None


def test_learning_curve_is_cumulative_and_windowed():
    tasks = [task(i, "early" if i < 3 else "late", 1000, 1000 if i >= 2 else 0, review={"rules": i, "pending": 0}) for i in range(6)]
    rows = learning_curve(arm(tasks), window=2)
    assert [r["task_index"] for r in rows] == list(range(6))
    assert rows[0]["e_cumulative"] == 0.0 and rows[5]["e_cumulative"] == pytest.approx(4000 / 6000)
    assert rows[2]["e_window"] == pytest.approx(0.5) and rows[3]["e_window"] == 1.0
    assert rows[4]["rules_learned"] == 4


def test_report_files(tmp_path):
    tasks = [task(0, "early", 1000, 0), task(1, "late", 1000, 500)]
    a = arm(tasks)
    results = {"options": {"upstream": "mock", "reviews_per_task": 2, "reviewer_error_rate": 0.0, "cache_block_tokens": 64},
               "tasks": [{"id": t["task_id"], "index": t["index"], "phase": t["phase"], "repo": "slugkit"} for t in tasks],
               "arms": {"mint": a}, "summaries": {"mint": summarize(a, 0.04)}}
    write_tables(tmp_path, results)
    rows = list(csv.reader(io.StringIO((tmp_path / "learning_curve.csv").read_text(encoding="utf-8"))))
    assert rows[0][:4] == ["arm", "task_index", "task_id", "phase"] and len(rows) == 3
    md = summary_markdown(results)
    assert "| 3. Mint |" in md and "No canary reached a Contributor request" in md
    assert pct(0.1234) == "12.3%" and pct(None) == "n/a"


def _results_with(reasons, e_contributor=500, violations=0):
    t = task(0, "early", 1000, e_contributor, violations=violations)
    t["per_request"] = [{"lane": lane, "reason": reason, "prompt": 0, "cached": 0, "completion": 0, "masked": 0}
                        for lane, reason in reasons]
    a = arm([t])
    return {"options": {"upstream": "mock", "reviews_per_task": 2, "reviewer_error_rate": 0.0, "cache_block_tokens": 64},
            "tasks": [{"id": t["task_id"], "index": 0, "phase": "early", "repo": "slugkit"}],
            "arms": {"mint": a}, "summaries": {"mint": summarize(a, 0.04)}}


def test_before_after_table_compares_arms_that_exist_in_both_runs():
    before = _results_with([("standard", "1 message(s) not contributable")], e_contributor=800, violations=8)
    after = _results_with([("standard", "1 message(s) not contributable [fingerprint]")], e_contributor=500)
    md = summary_markdown(after, before)
    assert "## Before and after the leak fix" in md
    assert "80.0% → 50.0%" in md and "8 → **0**" in md
    assert "## Before and after" not in summary_markdown(after)


def test_cause_table_counts_standard_requests_by_the_mechanism_in_the_reason():
    results = _results_with([("standard", "2 message(s) not contributable [output-path]"),
                             ("standard", "1 message(s) not contributable [fingerprint]"),
                             ("standard", "1 message(s) not contributable [fingerprint, output-path]"),
                             ("standard", "1 message(s) not contributable"),
                             ("contributor", "all context contributable after masking")])
    md = summary_markdown(results)
    assert "## Why requests stayed on Standard" in md
    assert "| 3. Mint | 4 | 1 | 1 | 1 | 1 |" in md
    assert "Why requests stayed" not in summary_markdown(_results_with([("standard", "1 message(s) not contributable")]))
