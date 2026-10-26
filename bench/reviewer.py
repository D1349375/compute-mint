"""The simulated reviewer: answers the gateway's review queue from the ground-truth labels.

Between tasks the reviewer looks at the files waiting in the queue (`GET /v1/review`) and decides
at most `budget` of them (a person does not review fifty files after every session). For each
item it knows the true label of the file. The review API only offers public | own_ip |
confidential, so FLOOR files are answered with `confidential`.

A decision becomes a path rule. The reviewer takes the gateway's suggested pattern (the file's
directory) only if every file that pattern would cover has the same answer; otherwise it labels
that one file. That is how a careful person would use "this folder is public".

`error_rate` makes the reviewer occasionally answer `public` whatever the truth is (a careless
click), which shows what the gateway can and cannot do about a wrong human decision.
"""
import fnmatch
import posixpath
import random
from dataclasses import dataclass, field

from compute_mint.labels import Label
from compute_mint.policy import FLOOR_FILES, normalize

from .repos import Repo, solution_files
from .tools import mount_for

API_NAMES = {Label.PUBLIC: "public", Label.OWN_IP: "own_ip", Label.CONFIDENTIAL: "confidential", Label.FLOOR: "confidential"}


def truth_paths(repos: dict[str, Repo], task_ids_by_repo: dict[str, list[str]]) -> dict[str, Label]:
    """Absolute path -> true label, for every file that exists or that a solution creates."""
    out: dict[str, Label] = {}
    for name, repo in repos.items():
        rels = set(repo.files) | set(repo.labels)
        for task_id in task_ids_by_repo.get(name, []):
            rels |= set(solution_files(task_id))
        for rel in sorted(rels):
            out[f"{mount_for(name)}/{rel}"] = repo.label_of(rel)
    return out


def is_floor_file(path: str) -> bool:
    base = posixpath.basename(path)
    return any(fnmatch.fnmatch(base, pat) for pat in FLOOR_FILES)


@dataclass
class Reviewer:
    truth: dict[str, Label]
    budget: int = 4
    error_rate: float = 0.0
    seed: int = 1
    decisions: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _pattern_for(self, path: str, suggested: str, answer: str) -> str:
        pat = normalize(suggested)
        for other, label in self.truth.items():
            if is_floor_file(other):
                continue   # credential files are FLOOR whatever the rules say
            if fnmatch.fnmatch(other, pat) and API_NAMES[label] != answer:
                return path
        return suggested

    def review(self, client, task_id: str = "") -> int:
        """Decide up to `budget` pending items through the gateway's review API; returns how many."""
        done = 0
        while done < self.budget:
            pending = client.get("/v1/review").json()["pending"]
            if not pending:
                break
            item = pending[0]
            path = item["path"]
            truth = self.truth.get(path, Label.CONFIDENTIAL)   # a file nobody described is treated as confidential
            answer = API_NAMES[truth]
            if self.error_rate and self._rng.random() < self.error_rate:
                answer = "public"
            pattern = self._pattern_for(path, item["suggested_pattern"], answer)
            r = client.post(f"/v1/review/{item['id']}", json={"label": answer, "pattern": pattern})
            r.raise_for_status()
            self.decisions.append({"after_task": task_id, "path": path, "truth": truth.name, "answer": answer,
                                   "pattern": pattern})
            done += 1
        return done
