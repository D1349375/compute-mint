"""The synthetic repositories: files, truth labels and canary strings.

Materials live in bench/materials/<repo>/ as

    files/          the repository as the agent sees it (path components starting with `_dot_`
                    stand for a leading dot, so .env and .gitignore can be committed)
    labels.json     the true sensitivity label of every file (what the owner would answer)
    canaries.json   every fake sensitive value, with the label it must never be sent under

Everything is invented; no real session content or personal data is used.
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from compute_mint.labels import Label

from . import BENCH_DIR

MATERIALS = BENCH_DIR / "materials"
SOLUTIONS = BENCH_DIR / "solutions"
ACCEPT = BENCH_DIR / "accept"

# How a session on each repo is declared to the gateway (x-cm-project / x-cm-dial). The public
# repo is published; for the private repo the owner contributes their own code but not
# third-party confidential or personal data. Individual tasks may narrow this (see Task.scope).
REPO_HEADERS = {
    "slugkit": {"project": "public", "dial": "public"},
    "billflow": {"project": "own_ip", "dial": "own_ip"},
}


def real_name(rel: str) -> str:
    """`docs/_dot_env` style names to real names."""
    return "/".join("." + part[5:] if part.startswith("_dot_") else part for part in rel.split("/"))


def stored_name(rel: str) -> str:
    return "/".join("_dot_" + part[1:] if part.startswith(".") and part not in (".", "..") else part
                    for part in rel.split("/"))


@dataclass(frozen=True)
class Canary:
    id: str
    value: str
    label: Label
    kind: str


@dataclass
class Repo:
    name: str
    files: dict[str, str]
    default_label: Label
    labels: dict[str, Label]
    canaries: list[Canary]
    headers: dict[str, str] = field(default_factory=dict)

    def label_of(self, path: str) -> Label:
        return self.labels.get(path, self.default_label)


def read_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts:
            rel = real_name(p.relative_to(root).as_posix())
            out[rel] = p.read_text(encoding="utf-8")
    return out


@lru_cache(maxsize=None)
def load_repo(name: str) -> Repo:
    base = MATERIALS / name
    labels_doc = json.loads((base / "labels.json").read_text(encoding="utf-8"))
    canary_doc = json.loads((base / "canaries.json").read_text(encoding="utf-8"))
    return Repo(
        name=name,
        files=read_tree(base / "files"),
        default_label=Label[labels_doc["default"]],
        labels={p: Label[l] for p, l in labels_doc["labels"].items()},
        canaries=[Canary(c["id"], c["value"], Label[c["label"]], c["kind"]) for c in canary_doc["canaries"]],
        headers=dict(REPO_HEADERS[name]),
    )


def repo_names() -> list[str]:
    return sorted(REPO_HEADERS)


def solution_files(task_id: str) -> dict[str, str]:
    return read_tree(SOLUTIONS / task_id)


def accept_files(task_id: str) -> dict[str, str]:
    return read_tree(ACCEPT / task_id)


def write_tree(files: dict[str, str], dest: Path) -> None:
    for rel, text in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
