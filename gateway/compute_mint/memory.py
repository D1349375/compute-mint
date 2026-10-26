"""Personal memory: preferences, project facts and accepted plans, in SQLite.

Every entry records where it came from (Origin) and how confidential it is (Label), so
whatever reads memory (recall, the project card, the Context Broker) can filter on both.
Content that contains credentials or personal data is stored with label FLOOR and is never
returned by default: reads cap the label at CONFIDENTIAL.

    python -m compute_mint.memory add preference "Reply in Traditional Chinese" --key language
    python -m compute_mint.memory search "chinese"
"""
import argparse
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .detect import has_floor
from .labels import Label, join
from .origin import Origin

KINDS = ("preference", "project_fact", "accepted_plan")

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',     -- '' = applies to every project
    key TEXT,                              -- optional stable name; (kind, project, key) is unique
    content TEXT NOT NULL,
    origin TEXT NOT NULL,
    label INTEGER NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS memory_key ON memory(kind, project, key) WHERE key IS NOT NULL;
"""


def default_path() -> Path:
    return Path(os.environ.get("CM_MEMORY_PATH") or Path(os.environ.get("CM_DATA_DIR", "data")) / "memory.sqlite")


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str
    project: str
    key: str | None
    content: str
    origin: Origin
    label: Label
    created: float
    updated: float

    def as_dict(self) -> dict:
        d = asdict(self)
        d["origin"], d["label"] = self.origin.value, self.label.name.lower()
        return d


def _row(r: tuple) -> Entry:
    return Entry(r[0], r[1], r[2], r[3], r[4], Origin(r[5]), Label(r[6]), r[7], r[8])


class Memory:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def add(self, kind: str, content: str, *, origin: Origin, label: Label = Label.OWN_IP,
            project: str = "", key: str | None = None) -> int:
        """Store an entry. An entry with the same (kind, project, key) is replaced in place."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        content = content.strip()
        if not content:
            raise ValueError("content is empty")
        label = join(label, Label.FLOOR) if has_floor(content) else label
        now = time.time()
        if key is not None:
            hit = self.db.execute("SELECT id FROM memory WHERE kind=? AND project=? AND key=?",
                                  (kind, project, key)).fetchone()
            if hit:
                self.db.execute("UPDATE memory SET content=?, origin=?, label=?, updated=? WHERE id=?",
                                (content, origin.value, int(label), now, hit[0]))
                self.db.commit()
                return hit[0]
        cur = self.db.execute(
            "INSERT INTO memory (kind, project, key, content, origin, label, created, updated) VALUES (?,?,?,?,?,?,?,?)",
            (kind, project, key, content, origin.value, int(label), now, now))
        self.db.commit()
        return cur.lastrowid

    def delete(self, entry_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memory WHERE id=?", (entry_id,))
        self.db.commit()
        return cur.rowcount > 0

    def entries(self, *, kind: str | None = None, project: str | None = None,
                max_label: Label = Label.CONFIDENTIAL, exclude_origins: tuple[Origin, ...] = ()) -> list[Entry]:
        """Entries in a stable order (kind, key, id). `project` also includes the global ('') entries."""
        where, args = ["label <= ?"], [int(min(max_label, Label.CONFIDENTIAL))]
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if project is not None:
            where.append("project IN ('', ?)")
            args.append(project)
        if exclude_origins:
            where.append(f"origin NOT IN ({','.join('?' * len(exclude_origins))})")
            args += [o.value for o in exclude_origins]
        rows = self.db.execute(
            f"SELECT id, kind, project, key, content, origin, label, created, updated FROM memory "
            f"WHERE {' AND '.join(where)} ORDER BY kind, COALESCE(key, ''), id", args).fetchall()
        return [_row(r) for r in rows]

    def search(self, query: str, *, limit: int = 5, project: str | None = None,
               max_label: Label = Label.CONFIDENTIAL, exclude_origins: tuple[Origin, ...] = ()) -> list[Entry]:
        """Keyword search: entries ranked by how many query terms they contain (case-insensitive).

        An empty query returns the most recently updated entries.
        """
        found = self.entries(project=project, max_label=max_label, exclude_origins=exclude_origins)
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return sorted(found, key=lambda e: -e.updated)[:limit]
        scored = []
        for e in found:
            hay = f"{e.key or ''} {e.content}".lower()
            score = sum(hay.count(t) > 0 for t in terms)
            if score:
                scored.append((score, e))
        scored.sort(key=lambda p: (-p[0], -p[1].updated, p[1].id))
        return [e for _, e in scored[:limit]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compute_mint.memory", description="Personal memory")
    ap.add_argument("--db", default=None, help="SQLite path (default: $CM_MEMORY_PATH or data/memory.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("kind", choices=KINDS)
    add.add_argument("content")
    add.add_argument("--project", default="")
    add.add_argument("--key")
    add.add_argument("--origin", default="user", choices=[o.value for o in Origin])
    add.add_argument("--label", default="own_ip", choices=["public", "own_ip", "confidential"])
    ls = sub.add_parser("list")
    ls.add_argument("--project")
    se = sub.add_parser("search")
    se.add_argument("query")
    se.add_argument("--project")
    rm = sub.add_parser("delete")
    rm.add_argument("id", type=int)
    args = ap.parse_args(argv)

    mem = Memory(args.db or default_path())
    if args.cmd == "add":
        eid = mem.add(args.kind, args.content, origin=Origin(args.origin), label=Label[args.label.upper()],
                      project=args.project, key=args.key)
        print(f"stored #{eid}")
    elif args.cmd == "delete":
        print("deleted" if mem.delete(args.id) else "not found")
    else:
        items = mem.entries(project=args.project) if args.cmd == "list" else mem.search(args.query, project=args.project)
        for e in items:
            print(f"#{e.id} [{e.kind}/{e.project or '*'}] ({e.origin.value}, {e.label.name.lower()}) "
                  f"{e.key + ': ' if e.key else ''}{e.content}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
