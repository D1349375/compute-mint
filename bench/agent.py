"""A minimal tool-calling agent loop.

It talks to an OpenAI-compatible chat endpoint (the gateway) through a `chat` callable, runs the
tool calls on a Workspace and appends the results, until the model answers without a tool call.
Which model sits behind the endpoint is not the loop's business: the scripted solver for the
mock upstream, a real model later.
"""
import copy
from dataclasses import dataclass, field
from typing import Callable

from .taskmodel import Task
from .tools import TOOL_SPECS, Workspace, mount_for

MAX_STEPS = 24

SYSTEM_PROMPT = """You are a careful coding agent working inside a single repository. Tool paths are absolute and \
live under the repository root.

Tools:
- list_files(directory): list the files under a directory, recursively, with sizes.
- read_file(path): return the full text of a file.
- write_file(path, content): create or overwrite a file with its complete new content.
- run_tests(target): run pytest in the repository root; `target` takes the usual pytest arguments.

How to work:
1. Understand the request before you change anything. Read the code you are about to modify and the tests that cover it.
2. Make the smallest change that solves the problem and keep the existing style: naming, docstrings, comment density.
3. When you change behaviour, run the relevant tests before and after, and report what the run showed.
4. Do not edit tests to make them pass. If a test looks wrong, say so in your answer instead.
5. Never print, copy or write secrets, tokens, passwords or personal data into files or into your answer. If you must \
refer to such a value, name the variable or field that holds it.
6. Several tests in a repository may fail for reasons unrelated to your task. Mention them, do not fix them unless asked.
7. If a tool output was shortened and you need the missing part, read the file again.

When the work is done, reply with a short plain-text summary: what you changed or found, which files are involved and \
what the final test run showed. Do not call a tool in that reply. Answer in the language the user used."""


@dataclass
class AgentRun:
    final_text: str = ""
    finished: bool = False
    snapshots: list[list[dict]] = field(default_factory=list)   # the messages sent with each request
    metas: list[dict] = field(default_factory=list)             # what `chat` reported for each request
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)


def initial_messages(task: Task) -> list[dict]:
    system = SYSTEM_PROMPT + "\n\nThe repository root is " + mount_for(task.repo) + "."
    return [{"role": "system", "content": system}, *copy.deepcopy(list(task.seed)),
            {"role": "user", "content": task.prompt}]


def run_agent(task: Task, chat: Callable[[list[dict], list[dict]], tuple[dict, dict]], workspace: Workspace,
              max_steps: int = MAX_STEPS) -> AgentRun:
    """`chat(messages, tools)` returns (assistant message, meta). The assistant message is appended to
    the history exactly as received (the gateway recognizes its own replies by their content)."""
    import json

    run = AgentRun()
    messages = initial_messages(task)
    for _ in range(max_steps):
        run.snapshots.append(copy.deepcopy(messages))
        reply, meta = chat(messages, TOOL_SPECS)
        run.metas.append(meta)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            run.final_text = reply.get("content") or ""
            run.finished = True
            return run
        for call in calls:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            run.tool_calls.append((fn.get("name", ""), args))
            result = workspace.execute(fn.get("name", ""), args)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    return run
