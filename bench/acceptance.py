"""Deterministic acceptance of a finished task: pytest runs, regex checks on the answer or on a file.
No model is involved in judging."""
import re
from pathlib import Path

from .repos import accept_files, write_tree
from .taskmodel import Task
from .tools import run_pytest


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.M | re.S) is not None


def evaluate(task: Task, root: Path, final_text: str) -> dict:
    """Check `task` against the repository at `root` and the agent's final answer. Held-out files from
    bench/accept/<task id>/ are copied into the repository first (after the agent has finished)."""
    write_tree(accept_files(task.id), root)
    results = []
    for check in task.checks:
        kind = check["type"]
        if kind == "pytest":
            code, out = run_pytest(root, check["args"])
            results.append({"type": kind, "args": check["args"], "passed": code == 0,
                            "detail": "" if code == 0 else out.strip().splitlines()[-1] if out.strip() else "no output"})
        elif kind == "answer":
            missing = [p for p in check["all"] if not _matches(p, final_text)]
            forbidden = [p for p in check["none"] if _matches(p, final_text)]
            results.append({"type": kind, "passed": not missing and not forbidden,
                            "detail": "" if not (missing or forbidden) else f"missing={missing} forbidden={forbidden}"})
        elif kind == "file":
            path = root / check["path"]
            text = path.read_text(encoding="utf-8") if path.is_file() else None
            if text is None:
                results.append({"type": kind, "path": check["path"], "passed": False, "detail": "file missing"})
                continue
            missing = [p for p in check["all"] if not _matches(p, text)]
            forbidden = [p for p in check["none"] if _matches(p, text)]
            results.append({"type": kind, "path": check["path"], "passed": not missing and not forbidden,
                            "detail": "" if not (missing or forbidden) else f"missing={missing} forbidden={forbidden}"})
        else:
            raise ValueError(f"unknown check type {kind}")
    return {"passed": all(r["passed"] for r in results), "checks": results}
