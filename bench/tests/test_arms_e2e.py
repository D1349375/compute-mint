"""End to end: the agent loop, the gateway, the mock upstream, the canary check and the arms, on a handful of tasks."""
import json
import socket
import subprocess
import sys

import pytest

from bench import BENCH_DIR
from bench.arms import run_arm
from bench.armtypes import ARM_SPECS, CONTRIBUTOR_MODEL, RunOptions
from bench.metrics import summarize
from bench.naive import analyze_naive, switch_point
from bench.run import main, run_bench
from bench.taskmodel import ANSWER, READ, IndexedTask, Task, answer_check
from bench.taskset import select

IDS = ["T01", "T02", "T08", "T14", "T18", "T36"]
LEAK_VECTOR_TASKS = {"T14-notify-singular-day", "T20-exporter-quoting", "T26-clients-find-case"}


@pytest.fixture(scope="module")
def tasks():
    return select(IDS)


@pytest.fixture(scope="module")
def runs(tasks):
    opts = RunOptions()
    out = {name: run_arm(ARM_SPECS[name], tasks, opts) for name in ("standard", "mint", "mint_broker", "mint_learn")}
    out["naive"] = analyze_naive(tasks, out["standard"], "mid")
    return out


def by_id(run):
    return {t["task_id"]: t for t in run.tasks}


def test_every_task_passes_in_every_executed_arm(runs):
    for name in ("standard", "mint", "mint_broker", "mint_learn"):
        failed = [t["task_id"] for t in runs[name].tasks if not t["passed"]]
        assert failed == [], (name, failed)
        assert all(t["finished"] for t in runs[name].tasks)


def test_all_standard_arm_never_uses_contributor_and_its_ledger_is_its_own_counterfactual(runs):
    std = runs["standard"]
    assert all(t["tokens"]["contributor"] == 0 and t["lanes"]["contributor"] == 0 for t in std.tasks)
    assert sum(t["cost"] for t in std.tasks) == pytest.approx(sum(t["counterfactual"] for t in std.tasks))
    assert std.violations == [] and std.origin_violations == 0
    assert std.sent_checks["contributor_requests_seen"] == 0


def test_what_the_ledger_says_left_the_machine_is_what_the_recorder_saw(runs):
    for name in ("mint", "mint_broker", "mint_learn"):
        chk = runs[name].sent_checks
        assert chk["payloads_identical"] and chk["contributor_requests_ledger"] == chk["contributor_requests_seen"] > 0


def test_resumed_session_with_claude_turns_stays_on_standard_in_every_arm(runs):
    for name in ("mint", "mint_broker", "mint_learn"):
        t = by_id(runs[name])["T01-slug-max-length"]
        assert t["lanes"]["contributor"] == 0 and t["passed"]
        assert t["origin_violations"] == 0


def test_masked_email_in_the_prompt_is_restored_in_the_answer(runs):
    t = by_id(runs["mint_learn"])["T36-currency-keyerror-email"]
    assert t["lanes"]["contributor"] == 2 and t["masked_spans"] >= 1
    assert t["passed"]   # the acceptance requires the real address in the final answer


def test_credentials_read_by_the_agent_never_reach_contributor(runs):
    for name in ("mint", "mint_broker", "mint_learn"):
        t = by_id(runs[name])["T18-publish-401"]
        assert t["violations"] == 0
        assert t["lanes"]["standard"] >= 1
    assert not any(v["canary"].startswith("pub-") for name in ("mint", "mint_broker", "mint_learn") for v in runs[name].violations)


def test_no_canary_gets_through_in_the_small_set(runs):
    """The small set holds T14, a leak-vector task; its customer names were never read in this set, so only the
    paths printed by the test run stand between them and Contributor (see the known-limit test below)."""
    for name in ("mint", "mint_broker"):
        assert runs[name].violations == []
    assert {v["task_id"] for v in runs["mint_learn"].violations} <= LEAK_VECTOR_TASKS


LEAK_IDS = ["T04", "T14", "T20", "T26"]   # T04 reads the client register, T14/T20/T26 print customer names in a test failure


@pytest.fixture(scope="module")
def leak_runs():
    tasks = select(LEAK_IDS)
    return {name: run_arm(ARM_SPECS[name], tasks, RunOptions())
            for name in ("mint", "mint_broker", "mint_learn", "oracle", "learn_nofix", "learn_fp")}


def test_the_test_output_leak_is_closed_in_every_mint_arm(leak_runs):
    for name in ("mint", "mint_broker", "mint_learn", "oracle", "learn_fp"):
        assert leak_runs[name].violations == [], name
        assert all(t["passed"] for t in leak_runs[name].tasks)


def test_the_gateway_without_the_fix_still_leaks_the_same_names(leak_runs):
    """`learn_nofix` is arm 5 on the gateway as it was: path rules for tool-call arguments only."""
    before = leak_runs["learn_nofix"]
    assert {v["task_id"] for v in before.violations} == LEAK_VECTOR_TASKS
    assert {v["where"].split(" (message")[0].split("(")[0].strip() for v in before.violations} == {"tool: run_tests"}
    assert {"customer_name", "person_name"} <= {v["kind"] for v in before.violations}


def test_fingerprints_cost_only_the_requests_that_carried_the_names(leak_runs):
    """Same reviewer, same tasks: the tokens that moved from Contributor to Standard are those of the three leaking tasks."""
    nofix, fixed = by_id(leak_runs["learn_nofix"]), by_id(leak_runs["learn_fp"])
    moved = {tid for tid in nofix if nofix[tid]["tokens"]["contributor"] != fixed[tid]["tokens"]["contributor"]}
    assert moved == LEAK_VECTOR_TASKS
    assert all(fixed[tid]["tokens"]["contributor"] < nofix[tid]["tokens"]["contributor"] for tid in moved)


def test_known_limit_names_the_gateway_never_saw_still_pass():
    """Honest limit of the deterministic fix: if the agent never read the register through the gateway, nothing ties the
    names in the test output to anything sensitive (only a semantic judge could). This pins the limit so a change in it is noticed."""
    run = run_arm(ARM_SPECS["oracle"], select(["T14"]), RunOptions())      # every path rule known: the test file is fine
    assert {v["task_id"] for v in run.violations} == {"T14-notify-singular-day"}


def test_rule_learning_moves_later_tasks_to_contributor(runs):
    plain, learned = by_id(runs["mint_broker"]), by_id(runs["mint_learn"])
    later = "T08-duedates-eom"   # same package as T02, which the reviewer has looked at by then
    assert learned[later]["lanes"]["contributor"] > plain[later]["lanes"]["contributor"]
    assert summarize(runs["mint_learn"].to_dict(), None)["e"] > summarize(runs["mint_broker"].to_dict(), None)["e"]
    assert runs["mint_learn"].reviewer_decisions and runs["mint"].reviewer_decisions == []


def test_broker_arm_does_not_hurt_acceptance_and_never_inflates_the_context(runs):
    s = summarize(runs["mint_broker"].to_dict(), None)
    assert s["pass_rate"] == 1.0 and s["broker_ratio"] <= 1.0
    assert summarize(runs["mint"].to_dict(), None)["broker_ratio"] == 1.0


def test_naive_arm_counts_what_would_have_left(runs):
    naive = by_id(runs["naive"])
    # T18 reads .env: after the switch the raw history, with both secrets in it, would go to Contributor
    t18 = naive["T18-publish-401"]
    assert t18["violations"] >= 2 and t18["passed"] is None
    assert t18["tokens"]["contributor_unchecked"] > t18["tokens"]["contributor"]
    # the resumed session carries Claude's turns: origin violations, no canaries needed
    assert naive["T01-slug-max-length"]["origin_violations"] >= 1
    # the same task, handled by the gateway arms, leaks nothing
    assert all(by_id(runs[n])["T18-publish-401"]["violations"] == 0 for n in ("mint", "mint_broker", "mint_learn"))


def test_naive_switch_points():
    assert [switch_point(p, 6) for p in ("start", "mid", "late")] == [0, 3, 5]
    assert switch_point("mid", 1) == 0 and switch_point("mid", 2) == 1


def test_naive_module_cannot_send_anything():
    code = ("import sys, bench.naive\n"
            "bad = [m for m in ('httpx', 'fastapi', 'starlette', 'requests', 'urllib3', 'bench.upstream', 'bench.arms') "
            "if m in sys.modules]\n"
            "print(bad)\n")
    root = BENCH_DIR.parent
    out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path[:0] = [%r, %r]\n%s" % (str(root), str(root / 'gateway'), code)],
                         capture_output=True, text=True, cwd=root)
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def block_external_network(monkeypatch):
    """Any connection or name lookup beyond the loopback interface (which asyncio uses internally) fails the test."""
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise AssertionError(f"network access attempted: {address}")
        return real_connect(self, address, *a, **k)

    def getaddrinfo(host, *a, **k):
        if host not in LOOPBACK:
            raise AssertionError(f"name lookup attempted: {host}")
        return real_getaddrinfo(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def test_no_network_is_needed_or_touched(tasks, monkeypatch):
    block_external_network(monkeypatch)
    results = run_bench(["standard", "mint", "naive"], RunOptions(), ["T02", "T36"])
    assert results["summaries"]["mint"]["pass_rate"] == 1.0


def test_same_configuration_gives_identical_results():
    a = run_bench(["standard", "mint_learn", "naive"], RunOptions(), ["T02", "T08", "T36"])
    b = run_bench(["standard", "mint_learn", "naive"], RunOptions(), ["T02", "T08", "T36"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _register_reads(i: int) -> IndexedTask:
    task = Task(id=f"X{i:02d}-read-register", repo="billflow", kind="explain", title="read the client register",
                prompt="Show me what the client register contains.",
                steps=(READ("config/clients.json"), ANSWER("done")), checks=(answer_check("done"),))
    return IndexedTask(task, i, "early")


def test_canary_check_catches_a_deliberately_wrong_review_decision():
    """A careless reviewer calls the client register public; the next session then sends it to Contributor.
    The gateway cannot know better (names are not detectable), the canary check must see it."""
    tasks = (_register_reads(1), _register_reads(2))
    careless = run_arm(ARM_SPECS["mint_learn"], tasks, RunOptions(reviewer_error_rate=1.0, reviews_per_task=5))
    kinds = {v["kind"] for v in careless.violations}
    assert {v["task_id"] for v in careless.violations} == {"X02-read-register"}
    assert {"customer_name", "person_name", "tax_id"} <= kinds
    assert careless.tasks[0]["violations"] == 0 and careless.tasks[1]["violations"] > 0
    # the emails in the same file were masked by the gateway, so they are not among the leaks
    assert "email" not in kinds and "phone" not in kinds

    careful = run_arm(ARM_SPECS["mint_learn"], tasks, RunOptions(reviewer_error_rate=0.0, reviews_per_task=5))
    assert careful.violations == []
    assert careful.tasks[1]["lanes"]["contributor"] < careless.tasks[1]["lanes"]["contributor"]


def test_cli_writes_the_result_files(tmp_path, capsys):
    rc = main(["--arms", "standard,mint,naive", "--tasks", "T02,T18", "--out", str(tmp_path), "--run-id", "unit"])
    assert rc == 0
    out = tmp_path / "unit"
    assert {p.name for p in out.iterdir()} == {"results.json", "tasks.csv", "learning_curve.csv", "violations.csv",
                                               "summary.md", "meta.json"}
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(results["arms"]) == {"standard", "mint", "naive"}
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "Canary violations" in md and "Naive switch" in md
    header = (out / "learning_curve.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("arm,task_index,task_id,phase,e_task,e_cumulative")
    assert "unit" in capsys.readouterr().out


def test_meta_upstream_is_reserved_and_makes_no_call(capsys, monkeypatch):
    block_external_network(monkeypatch)
    assert main(["--arms", "all", "--upstream", "meta"]) == 2
    assert "reserved" in capsys.readouterr().err
    from bench.upstream import make_upstream
    with pytest.raises(NotImplementedError):
        make_upstream("meta")


def test_what_if_shim_closes_the_test_output_gap_at_a_price():
    """Treating tool output that names no file as unreviewed removes the leak and costs contributable share.
    The shim only changes one app's policy instance; the gateway source is not involved. T02 + T14 is the
    case the gateway's own fix cannot see (the names were never read), so `mint_learn` still leaks here."""
    tasks = select(["T02", "T14"])
    plain = run_arm(ARM_SPECS["mint_learn"], tasks, RunOptions())
    strict = run_arm(ARM_SPECS["mint_strict"], tasks, RunOptions())
    assert plain.violations and strict.violations == []
    assert summarize(strict.to_dict(), None)["e"] < summarize(plain.to_dict(), None)["e"]
    assert all(t["passed"] for t in strict.tasks)


def test_results_do_not_depend_on_the_hash_seed():
    """Two processes with different PYTHONHASHSEED values must write byte-identical results."""
    code = ("import json, sys\n"
            "sys.path[:0] = [%r, %r]\n"
            "from bench.armtypes import RunOptions\n"
            "from bench.run import run_bench\n"
            "print(json.dumps(run_bench(['standard', 'mint_learn', 'oracle', 'naive'], RunOptions(), ['T02', 'T04', 'T14', 'T36']), sort_keys=True))\n"
            % (str(BENCH_DIR.parent), str(BENCH_DIR.parent / "gateway")))
    outs = []
    for seed in ("1", "2"):
        env = {**__import__("os").environ, "PYTHONHASHSEED": seed}
        outs.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=BENCH_DIR.parent, env=env).stdout)
    assert outs[0] and outs[0] == outs[1]
