import json

from bench.agent import initial_messages, run_agent
from bench.repos import load_repo
from bench.solver import RECALL, ScriptedSolver
from bench.taskset import get_task
from bench.tools import Workspace, mount_for


def ws(root, repo="billflow"):
    return Workspace(root, mount_for(repo))


def test_tools_work_on_absolute_and_relative_paths_and_stay_inside_the_repo(workspace_factory):
    root = workspace_factory("billflow")
    w = ws(root)
    assert w.read_file("/work/billflow/billflow/money.py") == w.read_file("billflow/money.py")
    assert w.read_file("../etc/passwd").startswith("error")
    assert w.read_file("/etc/passwd").startswith("error")
    assert w.read_file("C:/Windows/win.ini").startswith("error")
    assert "wrote" in w.write_file("/work/billflow/new/dir/x.txt", "hi\n")
    assert (root / "new/dir/x.txt").read_text() == "hi\n"
    assert w.write_file("../outside.txt", "x").startswith("error")
    assert not (root.parent / "outside.txt").exists()


def test_list_files_shows_absolute_paths_and_skips_caches(workspace_factory):
    root = workspace_factory("slugkit")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"x")
    out = ws(root, "slugkit").list_files("/work/slugkit")
    assert "/work/slugkit/slugkit/slug.py" in out and "/work/slugkit/.env" in out
    assert "__pycache__" not in out


def test_run_tests_output_is_stable_and_free_of_machine_specific_text(workspace_factory):
    a, b = workspace_factory("slugkit"), workspace_factory("slugkit")
    out_a = ws(a, "slugkit").run_tests("tests/test_slug.py")
    out_b = ws(b, "slugkit").run_tests("tests/test_slug.py")
    assert out_a == out_b
    assert "tests/test_slug.py" in out_a and "\\" not in out_a
    assert str(a) not in out_a and "bench-test-" not in out_a
    assert " in Xs" in out_a and "[exit code: 1]" in out_a


def test_run_tests_runs_in_a_clean_environment(workspace_factory, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "should-not-reach-the-child")
    root = workspace_factory("slugkit")
    (root / "tests" / "test_env.py").write_text(
        "import os\ndef test_env():\n    assert 'META_API_KEY' not in os.environ\n", encoding="utf-8")
    assert "[exit code: 0]" in ws(root, "slugkit").run_tests("tests/test_env.py")


def test_unknown_tool_and_missing_argument_are_reported_not_raised(workspace_factory):
    w = ws(workspace_factory("slugkit"), "slugkit")
    assert w.execute("nope", {}).startswith("error")
    assert w.execute("read_file", {}).startswith("error")


def _history(task, solver, workspace):
    """Drive the solver without any gateway: apply its tool calls and append the outputs."""
    messages = initial_messages(task)
    for _ in range(30):
        reply = solver.reply(messages)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return messages
        for call in calls:
            fn = call["function"]
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": workspace.execute(fn["name"], json.loads(fn["arguments"]))})
    raise AssertionError("solver did not finish")


def test_solver_replays_the_script_and_answers(workspace_factory):
    task = get_task("T02-money-split").task
    root = workspace_factory("billflow")
    from bench.repos import solution_files
    messages = _history(task, ScriptedSolver(task, solution_files(task.id)), ws(root))
    names = [c["function"]["name"] for m in messages if m.get("tool_calls") for c in m["tool_calls"]]
    assert names == ["run_tests", "read_file", "write_file", "run_tests"]
    assert "split_amount" in messages[-1]["content"]
    assert "[exit code: 0]" in messages[-2]["content"]


def test_solver_rereads_a_file_whose_output_was_compacted(workspace_factory):
    task = get_task("T32-contract-payment-terms").task
    from bench.repos import solution_files
    solver = ScriptedSolver(task, solution_files(task.id))
    root = workspace_factory("billflow")
    messages = _history(task, solver, ws(root))
    # the full history lets it answer without a second read
    calls = [c["id"] for m in messages if m.get("tool_calls") for c in m["tool_calls"]]
    assert not any(i.startswith(RECALL) for i in calls)

    # compact the contract output, the way the Context Broker would, and ask again
    squeezed = json.loads(json.dumps(messages[:-1]))
    for m in squeezed:
        if m.get("role") == "tool" and "Master services agreement" in m["content"]:
            m["content"] = m["content"][:300] + "\n[compute-mint: 3000 chars omitted]\n" + m["content"][-300:]
    reply = solver.reply(squeezed)
    assert reply["tool_calls"][0]["id"].startswith(RECALL)
    assert json.loads(reply["tool_calls"][0]["function"]["arguments"])["path"].endswith("client-c101-msa-summary.md")

    # after the re-read it answers, quoting from the fresh output
    squeezed.append(reply)
    squeezed.append({"role": "tool", "tool_call_id": reply["tool_calls"][0]["id"],
                     "content": load_repo("billflow").files["contracts/client-c101-msa-summary.md"]})
    final = solver.reply(squeezed)
    assert "net 45 days from the statement date" in final["content"]


def test_solver_quotes_what_it_sees_including_placeholders():
    task = get_task("T36-currency-keyerror-email").task
    from bench.repos import solution_files
    solver = ScriptedSolver(task, solution_files(task.id))
    masked = initial_messages(task)
    masked[-1] = {"role": "user", "content": task.prompt.replace("finance@marrowgate.example", "⟨EMAIL_1⟩")}
    masked += [{"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": "/work/billflow/billflow/billrun.py"})}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "..."}]
    assert "⟨EMAIL_1⟩" in solver.reply(masked)["content"]


def test_agent_loop_stops_at_a_text_reply_and_keeps_every_request_snapshot(workspace_factory):
    task = get_task("T16-lru-get-recency").task
    from bench.repos import solution_files
    solver = ScriptedSolver(task, solution_files(task.id))

    def chat(messages, tools):
        return solver.reply(messages), {"lane": "standard"}

    run = run_agent(task, chat, ws(workspace_factory("slugkit"), "slugkit"))
    assert run.finished and run.final_text
    assert len(run.snapshots) == len(run.metas) == 5   # run, read, write, run, answer
    assert [len(s) for s in run.snapshots] == sorted(len(s) for s in run.snapshots)
    assert run.snapshots[0][0]["role"] == "system" and run.snapshots[0][-1]["content"] == task.prompt
