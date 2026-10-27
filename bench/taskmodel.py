"""Task and step definitions.

A task is a prompt, a deterministic acceptance check and a *script*: the sequence of tool calls
the scripted solver issues (the simulated model), ending in a final answer. Writes come from
bench/solutions/<task id>/, so the same files make the acceptance pass in the tests.
"""
from dataclasses import dataclass, field

PROMPT = "@prompt"   # pseudo path for quotes: the task's own user message


@dataclass(frozen=True)
class Step:
    kind: str                      # list | read | run | write | answer
    arg: str = ""                  # directory, path or pytest arguments
    text: str = ""                 # answer template: {0}, {1}, ... are filled from `quotes`
    quotes: tuple = ()             # ((path, regex), ...): group 1 of the first match in what the model has seen


def LIST(directory: str = ".") -> Step:
    return Step("list", directory)


def READ(path: str) -> Step:
    return Step("read", path)


def RUN(target: str = "") -> Step:
    return Step("run", target)


def WRITE(path: str) -> Step:
    return Step("write", path)


def ANSWER(text: str, *quotes: tuple[str, str]) -> Step:
    return Step("answer", text=text, quotes=tuple(quotes))


# --- acceptance checks (plain dicts so they serialize into the results) ---

def pytest_check(*args: str) -> dict:
    """pytest must exit 0 for these arguments (held-out files from bench/accept/<id>/ are in place)."""
    return {"type": "pytest", "args": list(args)}


def answer_check(*patterns: str, none: tuple[str, ...] = ()) -> dict:
    """The final answer must match every pattern and none of the `none` patterns (regex, case-sensitive)."""
    return {"type": "answer", "all": list(patterns), "none": list(none)}


def file_check(path: str, *patterns: str, none: tuple[str, ...] = ()) -> dict:
    """The file must exist and match every pattern (multiline) and none of the `none` patterns."""
    return {"type": "file", "path": path, "all": list(patterns), "none": list(none)}


@dataclass(frozen=True)
class Task:
    id: str
    repo: str
    kind: str                      # bug | feature | explain | docs
    title: str
    prompt: str
    steps: tuple[Step, ...]
    checks: tuple[dict, ...]
    scope: str = "repo"            # "repo": the repo's labels apply; "public": the user scopes this session to public work
    seed: tuple[dict, ...] = ()    # earlier turns written by another assistant (a resumed session)
    seed_client: str = "anthropic" # model that wrote the seed turns (x-cm-client)
    tags: tuple[str, ...] = ()
    lang: str = "en"

    def headers(self, repo_headers: dict[str, str]) -> dict[str, str]:
        project, dial = repo_headers["project"], repo_headers["dial"]
        if self.scope == "public":
            project, dial = "public", "public"
        h = {"x-cm-project": project, "x-cm-dial": dial}
        if self.seed:
            h["x-cm-client"] = self.seed_client
        return h

    @property
    def answer_step(self) -> Step:
        return self.steps[-1]


@dataclass
class IndexedTask:
    """A task with its place in the timeline."""
    task: Task
    index: int                     # 0-based position in time order
    phase: str                     # early | late


def seed_note(text: str) -> tuple[dict, ...]:
    """A resumed-session seed: the user asks for the state of play, another assistant answers."""
    return ({"role": "user", "content": "Before I hand this over: what did you find so far?"},
            {"role": "assistant", "content": text})
