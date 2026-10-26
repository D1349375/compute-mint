"""Learned sensitivity labels: the user's review decisions become path rules.

When a tool output comes from a file the gateway has no rule for, and the project baseline
keeps it off Contributor, the path goes into a review queue. One decision ("docs/** is
public") turns into a rule, so the next request touching those files can be contributed.
This is the part of the flywheel the user drives: the more they use and review, the larger
the contributable share.

When several rules match a path, the strictest label wins.
"""
import fnmatch
import json
import posixpath
import sqlite3
from pathlib import Path

from .labels import Label, join

PATH_KEYS = ("path", "file_path", "filepath", "file", "filename", "notebook_path", "cwd")

# Files whose whole content is treated as FLOOR, whatever the rules say: regex detection only
# catches recognizable secrets, and these files hold the rest (hosts, user names, short tokens).
FLOOR_FILES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", ".npmrc",
               ".pypirc", ".netrc", "credentials", "credentials.json", "auth.json", "*.kdbx", "secrets.*")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    label INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    suggested_pattern TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'   -- pending | decided
);
"""


def normalize(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def paths_in_arguments(arguments: str | dict | None) -> list[str]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return []
    if not isinstance(arguments, dict):
        return []
    return [normalize(v) for k, v in arguments.items()
            if isinstance(v, str) and k.lower() in PATH_KEYS and v.strip()]


def tool_paths(messages: list[dict]) -> dict[int, list[str]]:
    """Index of each tool message -> file paths named in the tool call that produced it."""
    by_call: dict[str, list[str]] = {}
    for m in messages:
        for call in m.get("tool_calls") or []:
            by_call[call.get("id", "")] = paths_in_arguments((call.get("function") or {}).get("arguments"))
    return {i: by_call.get(m.get("tool_call_id", ""), [])
            for i, m in enumerate(messages) if m.get("role") == "tool"}


class Policy:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def rules(self) -> list[tuple[str, Label]]:
        return [(p, Label(l)) for p, l in self.db.execute("SELECT pattern, label FROM rules ORDER BY id")]

    def label_for(self, path: str) -> Label | None:
        if any(fnmatch.fnmatch(posixpath.basename(normalize(path)), f) for f in FLOOR_FILES):
            return Label.FLOOR
        hits = [label for pattern, label in self.rules() if fnmatch.fnmatch(normalize(path), pattern)]
        return join(*hits) if hits else None

    def set_rule(self, pattern: str, label: Label) -> None:
        self.db.execute("INSERT INTO rules (pattern, label) VALUES (?, ?) "
                        "ON CONFLICT(pattern) DO UPDATE SET label = excluded.label", (normalize(pattern), int(label)))
        self.db.commit()

    def baseline_for(self, messages: list[dict], default: Label, unknown_file: Label = Label.CONFIDENTIAL):
        """Per-message baseline.

        Tool outputs read from files use the learned rules; a file with no rule yet is treated
        as `unknown_file` (conservative) until the user reviews it. Everything else uses the
        project default.
        """
        paths = tool_paths(messages)

        def baseline(i: int, msg: dict) -> Label:
            file_paths = paths.get(i, [])
            if not file_paths:
                return default
            labels = [self.label_for(p) for p in file_paths]
            return join(*(l if l is not None else unknown_file for l in labels))
        return baseline

    def enqueue_unknown(self, messages: list[dict], indexes: list[int]) -> int:
        """Queue unruled file paths behind the given (blocked) messages for review."""
        paths = tool_paths(messages)
        added = 0
        for i in indexes:
            for p in paths.get(i, []):
                if self.label_for(p) is None:
                    suggested = posixpath.dirname(p) + "/**" if "/" in p else p
                    cur = self.db.execute("INSERT OR IGNORE INTO review (path, suggested_pattern) VALUES (?, ?)",
                                          (p, suggested))
                    added += cur.rowcount
        self.db.commit()
        return added

    def pending(self) -> list[dict]:
        rows = self.db.execute("SELECT id, path, suggested_pattern FROM review WHERE status = 'pending' ORDER BY id")
        return [{"id": i, "path": p, "suggested_pattern": s} for i, p, s in rows]

    def decide(self, item_id: int, label: Label, pattern: str | None = None) -> str:
        row = self.db.execute("SELECT suggested_pattern FROM review WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        pattern = pattern or row[0]
        self.set_rule(pattern, label)
        # One decision can settle every queued path it covers.
        for rid, path in self.db.execute("SELECT id, path FROM review WHERE status = 'pending'").fetchall():
            if fnmatch.fnmatch(path, normalize(pattern)):
                self.db.execute("UPDATE review SET status = 'decided' WHERE id = ?", (rid,))
        self.db.commit()
        return pattern
