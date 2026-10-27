"""Learned sensitivity labels: the user's review decisions become path rules.

When a tool output comes from a file the gateway has no rule for, and the project baseline
keeps it off Contributor, the path goes into a review queue. One decision ("docs/** is
public") turns into a rule, so the next request touching those files can be contributed.
This is the part of the flywheel the user drives: the more they use and review, the larger
the contributable share.

When several rules match a path, the strictest label wins.

Output that is not the content of one named file (a test run, a shell command) is labeled from
two further sources, because the project default says nothing about what such output contains:
the paths it names (`outpaths.py`: tracebacks, `path:line`, the command's own arguments), judged
by the same rules, and content fingerprints of sensitive text read earlier (`fingerprint.py`).
The strictest label wins.
"""
import fnmatch
import json
import posixpath
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .context import message_text
from .fingerprint import SCORE, SCORE_UNREVIEWED, THRESHOLD, FingerprintIndex
from .labels import Label, join
from .outpaths import PathRef, is_absolute, paths_in_text, resolve, root_from_text

PATH_KEYS = ("path", "file_path", "filepath", "file", "filename", "notebook_path", "cwd")
# Arguments that carry a working directory or a command line; they are evidence about the output
# of a tool call that names no file, not the identity of a file.
CWD_KEYS = ("cwd", "workdir", "working_dir", "working_directory")
COMMAND_KEYS = ("command", "cmd", "script", "args", "argv", "target", "targets")
ROOT_ROLES = ("system", "developer")

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
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | decided
    hits INTEGER NOT NULL DEFAULT 0          -- requests this path has held back
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


def _arguments(call: dict) -> dict:
    args = (call.get("function") or {}).get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return {}
    return args if isinstance(args, dict) else {}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def root_from_messages(messages: list[dict]) -> str | None:
    """Working directory announced in the system/developer messages or the first user message."""
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    for m in [m for m in messages if m.get("role") in ROOT_ROLES] + ([first_user] if first_user else []):
        root = root_from_text(message_text(m))
        if root:
            return root
    return None


def clean_root(value: str | None) -> str | None:
    """Validate a root given by the caller (x-cm-root): an absolute path, normalized."""
    if not value or not is_absolute(value.strip()):
        return None
    v = normalize(value.strip())
    return posixpath.normpath(v) if len(v) > 1 else None


@dataclass
class Evidence:
    """Where a tool message's text comes from, as far as the call and the text show."""
    identity: list[str] = field(default_factory=list)   # file named by the call: the message is that file's content
    command: list[str] = field(default_factory=list)    # paths named by the command line
    output: list[str] = field(default_factory=list)     # paths printed in the output
    unresolved: bool = False                            # a relative path that could not be placed

    @property
    def derived(self) -> list[str]:
        return [p for p in self.command + self.output if p not in self.identity]


class Baseline:
    """Per-message baseline label, plus why a message got a label stricter than the project default."""

    def __init__(self, default: Label, labels: list[Label], causes: list[tuple[str, ...]]) -> None:
        self.default, self.labels, self.causes = default, labels, causes

    def __call__(self, i: int, msg: dict | None = None) -> Label:
        return self.labels[i] if 0 <= i < len(self.labels) else self.default

    def why(self, i: int) -> tuple[str, ...]:
        return self.causes[i] if 0 <= i < len(self.causes) else ()


class Policy:
    def __init__(self, path: str | Path = ":memory:", *, output_paths: bool = True, fingerprints: bool = True,
                 fingerprint_threshold: int = THRESHOLD) -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        if "hits" not in {row[1] for row in self.db.execute("PRAGMA table_info(review)")}:   # database from before
            self.db.execute("ALTER TABLE review ADD COLUMN hits INTEGER NOT NULL DEFAULT 0")
        self.output_paths = output_paths
        self.impact_order = output_paths    # outputs name many more paths: review the ones that hold back most first
        self.index: FingerprintIndex | None = FingerprintIndex(fingerprint_threshold) if fingerprints else None

    def rules(self) -> list[tuple[str, Label]]:
        return [(p, Label(l)) for p, l in self.db.execute("SELECT pattern, label FROM rules ORDER BY id")]

    def _labeler(self):
        """label_for over a snapshot of the rules (one query per request instead of one per path)."""
        rules = self.rules()
        cache: dict[str, Label | None] = {}

        def label(path: str) -> Label | None:
            if path not in cache:
                p = normalize(path)
                if any(fnmatch.fnmatch(posixpath.basename(p), f) for f in FLOOR_FILES):
                    cache[path] = Label.FLOOR
                else:
                    hits = [l for pattern, l in rules if fnmatch.fnmatch(p, pattern)]
                    cache[path] = join(*hits) if hits else None
            return cache[path]
        return label

    def label_for(self, path: str) -> Label | None:
        return self._labeler()(path)

    def set_rule(self, pattern: str, label: Label) -> None:
        self.db.execute("INSERT INTO rules (pattern, label) VALUES (?, ?) "
                        "ON CONFLICT(pattern) DO UPDATE SET label = excluded.label", (normalize(pattern), int(label)))
        self.db.commit()

    # -- where does a tool message's text come from -------------------------------------------------

    def _known_paths(self, rel: str) -> list[str]:
        """Absolute paths already seen (review queue) that end with the relative path `rel`."""
        rows = self.db.execute("SELECT path FROM review WHERE path LIKE ? ORDER BY id", ("%/" + rel,)).fetchall()
        return [r[0] for r in rows if r[0].endswith("/" + rel)]

    def evidence(self, messages: list[dict], root: str | None = None) -> dict[int, Evidence]:
        """Index of each tool message -> Evidence. `root` (x-cm-root) overrides what the messages say."""
        root = root or root_from_messages(messages)
        calls = {}
        for m in messages:
            for call in m.get("tool_calls") or []:
                calls[call.get("id", "")] = (call.get("function") or {}).get("name", ""), _arguments(call)

        seen: list[str] = []          # absolute paths named by calls so far: for placing dirless and relative paths

        def place(ref: PathRef, base: str | None) -> tuple[list[str], bool]:
            """(absolute paths, unresolved) for one path found in a call or an output."""
            if ref.library:
                return [], False
            if not ref.dirless and ref.absolute:
                return [ref.path], False
            if not ref.dirless:
                full = resolve(ref, base)
                if full:
                    return [full], False
                known = [p for p in seen if p.endswith("/" + ref.path)] or self._known_paths(ref.path)
                return (known, False) if known else ([], True)
            # a bare file name: the call's directory if there is one, else names we already know
            if base:
                return [posixpath.normpath(base.rstrip("/") + "/" + ref.path)], False
            known = [p for p in seen if posixpath.basename(p) == ref.path]
            return (known, False) if known else ([], False)

        out: dict[int, Evidence] = {}
        for i, m in enumerate(messages):
            if m.get("role") != "tool":
                continue
            name, args = calls.get(m.get("tool_call_id", ""), ("", {}))
            call_base = next((normalize(v) for k, v in args.items() if k.lower() in CWD_KEYS and isinstance(v, str)
                              and is_absolute(normalize(v))), None) or root
            ev = Evidence()
            for p in paths_in_arguments(args):
                ref = PathRef(posixpath.normpath(p), is_absolute(p), False)
                paths, unresolved = place(ref, call_base)
                ev.identity += [x for x in (paths or ([p] if unresolved else [])) if x not in ev.identity]
            if not ev.identity and self.output_paths:
                for k, v in args.items():
                    if k.lower() in COMMAND_KEYS:
                        for s in _strings(v):
                            for ref in paths_in_text(s, command=True):
                                paths, unresolved = place(ref, call_base)
                                ev.command += [x for x in paths if x not in ev.command]
                                ev.unresolved |= unresolved
                for ref in paths_in_text(message_text(m)):
                    paths, unresolved = place(ref, call_base)
                    ev.output += [x for x in paths if x not in ev.output]
                    ev.unresolved |= unresolved
            seen += [p for p in ev.identity + ev.command if is_absolute(p) and p not in seen]
            out[i] = ev
        return out

    def baseline_for(self, messages: list[dict], default: Label, unknown_file: Label = Label.CONFIDENTIAL,
                     root: str | None = None) -> Baseline:
        """Per-message baseline.

        Tool outputs read from files use the learned rules; a file with no rule yet is treated
        as `unknown_file` (conservative) until the user reviews it. Output that is not one file's
        content gets the strictest of: the project default, the rule labels of the paths it
        names, and the label of sensitive text it repeats (content fingerprints). Everything
        else uses the project default.
        """
        label = self._labeler()
        evidence = self.evidence(messages, root)
        labels = [default] * len(messages)
        causes: list[tuple[str, ...]] = [()] * len(messages)

        def path_label(p: str) -> Label:
            l = label(p)
            return unknown_file if l is None else l

        for i, ev in evidence.items():
            if ev.identity:
                labels[i] = join(*(path_label(p) for p in ev.identity))
                continue
            found = [path_label(p) for p in ev.derived]
            if ev.unresolved:
                found.append(unknown_file)
            if found and join(*found) > default:
                labels[i] = join(default, *found)
                causes[i] = ("output-path",)

        if self.index is not None:
            self._fingerprints(messages, evidence, labels, causes, label, unknown_file)
        return Baseline(default, labels, causes)

    def _fingerprints(self, messages, evidence, labels, causes, label, unknown_file) -> None:
        index = self.index

        def live(source: str) -> Label:
            l = label(source)
            return unknown_file if l is None else l

        # 1. remember what sensitive sources said; what cleared files said stops being evidence
        for i, ev in evidence.items():
            sources = ev.identity or ev.command
            text = message_text(messages[i])
            for p in sources:
                if live(p) >= Label.CONFIDENTIAL:
                    index.add(p, text)
            if ev.identity and all(label(p) is not None and label(p) < Label.CONFIDENTIAL for p in ev.identity):
                index.clear(text)

        # 2. recognize it in text that is not itself a named file's content
        user_idx = next((i for i, m in enumerate(messages) if m.get("role") == "user"), -1)
        own_words = index.exempt_set(*(message_text(m) for i, m in enumerate(messages)
                                       if m.get("role") in ROOT_ROLES or i == user_idx))
        for i, m in enumerate(messages):
            role = m.get("role")
            if role == "tool":
                if evidence[i].identity:
                    continue
            elif not (role == "user" and i != user_idx):
                continue
            score, found = 0, Label.PUBLIC
            for match in index.matches(message_text(m), own_words):
                weight = 0
                for source in match.sources:
                    known = label(source)         # None: not reviewed yet, a weaker kind of evidence
                    live_label = unknown_file if known is None else known
                    if live_label >= Label.CONFIDENTIAL:
                        w = (SCORE_UNREVIEWED if known is None else SCORE)[match.kind]
                        if w:
                            weight = max(weight, w)
                            found = join(found, live_label)
                score += weight
            if score >= index.threshold and found > labels[i]:
                labels[i] = found
                causes[i] = causes[i] + ("fingerprint",)

    # -- review queue -------------------------------------------------------------------------------

    def enqueue_unknown(self, messages: list[dict], indexes: list[int], root: str | None = None) -> int:
        """Queue unruled file paths behind the given (blocked) messages for review."""
        evidence = self.evidence(messages, root)
        label = self._labeler()
        added = 0
        for i in indexes:
            ev = evidence.get(i)
            if ev is None:
                continue
            for p in ev.identity + ev.derived:
                if label(p) is None:
                    suggested = posixpath.dirname(p) + "/**" if "/" in p else p
                    cur = self.db.execute("INSERT OR IGNORE INTO review (path, suggested_pattern) VALUES (?, ?)",
                                          (p, suggested))
                    added += cur.rowcount
                    self.db.execute("UPDATE review SET hits = hits + 1 WHERE path = ? AND status = 'pending'", (p,))
        self.db.commit()
        return added

    def pending(self) -> list[dict]:
        order = "hits DESC, id" if self.impact_order else "id"
        rows = self.db.execute(f"SELECT id, path, suggested_pattern, hits FROM review WHERE status = 'pending' ORDER BY {order}")
        return [{"id": i, "path": p, "suggested_pattern": s, "hits": h} for i, p, s, h in rows]

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
