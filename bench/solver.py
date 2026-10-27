"""The scripted solver: the simulated model behind the mock upstream.

It does not solve anything by itself. For each task it replays the task's script (the tool
calls a competent agent would make) and, at the end, answers from what is in its context.
It behaves like a model in the ways that matter for the measurements:

- it reads only what the gateway sent it: a Contributor request carries masked text, so a
  value quoted from a tool output or from the prompt may be a placeholder, which the gateway
  restores in the reply;
- it answers from the context it was given. If a value it needs is no longer visible (the
  Context Broker compacted an old tool output) it re-reads the file once, like an agent would,
  which costs another request;
- writes come from bench/solutions/<task id>/.

What it does NOT model is a model's mistakes: a scripted solver never takes a wrong turn.
"""
import json
import re

from .taskmodel import PROMPT, Step, Task

RECALL = "recall_"


class SolverError(RuntimeError):
    pass


def _tool_calls(messages: list[dict]) -> list[tuple[str, str, dict]]:
    out = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            out.append((call.get("id", ""), fn.get("name", ""), args))
    return out


def mount_for(repo: str) -> str:
    return f"/work/{repo}"


def _find_value(messages: list[dict], task: Task, path: str, pattern: str) -> str | None:
    """Group 1 (or the whole match) of `pattern` in the latest text the model has seen for `path`."""
    rx = re.compile(pattern, re.M)
    if path == PROMPT:
        idx = 1 + len(task.seed)
        text = messages[idx].get("content") if idx < len(messages) else None
        m = rx.search(text) if isinstance(text, str) else None
        return (m.group(1) if m and m.groups() else m.group(0)) if m else None
    full = f"{mount_for(task.repo)}/{path}"
    wanted = [cid for cid, name, args in _tool_calls(messages) if name == "read_file" and args.get("path") == full]
    for cid in reversed(wanted):
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id") == cid and isinstance(msg.get("content"), str):
                m = rx.search(msg["content"])
                if m:
                    return m.group(1) if m.groups() else m.group(0)
    return None


class ScriptedSolver:
    def __init__(self, task: Task, solution: dict[str, str]) -> None:
        self.task = task
        self.solution = solution
        self.plan = [s for s in task.steps if s.kind != "answer"]

    def _call(self, step: Step, n: int, call_id: str | None = None) -> dict:
        mount = mount_for(self.task.repo)
        if step.kind == "list":
            name, args = "list_files", {"directory": mount if step.arg in ("", ".") else f"{mount}/{step.arg}"}
        elif step.kind == "read":
            name, args = "read_file", {"path": f"{mount}/{step.arg}"}
        elif step.kind == "run":
            name, args = "run_tests", {"target": step.arg}
        elif step.kind == "write":
            if step.arg not in self.solution:
                raise SolverError(f"{self.task.id}: no solution file for {step.arg}")
            name, args = "write_file", {"path": f"{mount}/{step.arg}", "content": self.solution[step.arg]}
        else:
            raise SolverError(f"unknown step kind {step.kind}")
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": call_id or f"call_{n}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}

    def reply(self, messages: list[dict]) -> dict:
        calls = _tool_calls(messages)
        regular = [c for c in calls if not c[0].startswith(RECALL)]
        mount = mount_for(self.task.repo)
        recalled = {args.get("path") for cid, _name, args in calls if cid.startswith(RECALL)}
        if len(regular) < len(self.plan):
            return self._call(self.plan[len(regular)], len(calls) + 1)

        final = self.task.answer_step
        values: list[str | None] = []
        for path, pattern in final.quotes:
            value = _find_value(messages, self.task, path, pattern)
            if value is None and path != PROMPT and f"{mount}/{path}" not in recalled:
                # the text is no longer in view (compacted): look at the file again
                return self._call(Step("read", path), len(calls) + 1, call_id=f"{RECALL}{len(calls) + 1}")
            values.append(value if value is not None else "<not found>")
        return {"role": "assistant", "content": final.text.format(*values)}


def reference_answer(task: Task, files: dict[str, str]) -> str:
    """The answer the solver gives when it can see everything (used by the tests to check that the
    acceptance passes under the correct solution). `files` is the repository content."""
    values = []
    for path, pattern in task.answer_step.quotes:
        text = task.prompt if path == PROMPT else files.get(path, "")
        m = re.search(pattern, text, re.M)
        values.append((m.group(1) if m and m.groups() else m.group(0)) if m else "<not found>")
    return task.answer_step.text.format(*values)
