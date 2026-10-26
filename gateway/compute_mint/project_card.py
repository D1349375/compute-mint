"""Project card: a generated block in AGENTS.md / CLAUDE.md built from personal memory.

Only the text between the markers is ever written; everything else in the file is kept as is.
The block is deterministic (no timestamps, stable order) so it does not change the prompt
prefix of agents that load the file. Update it between sessions, not during one:

    python -m compute_mint.project_card --project my-repo AGENTS.md CLAUDE.md
"""
import argparse
import re
import sys
from pathlib import Path

from .labels import Label
from .memory import KINDS, Entry, Memory, default_path
from .origin import NON_CONTRIBUTOR

START = "<!-- compute-mint:start -->"
END = "<!-- compute-mint:end -->"

HEADINGS = {"preference": "Preferences", "project_fact": "Project facts", "accepted_plan": "Accepted plans"}


class CardError(Exception):
    """The target file's markers are damaged; nothing is written."""


def _one_line(text: str) -> str:
    # Memory content must not be able to close the block or open a comment of its own.
    text = " ".join(text.split()).replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return text


def _line(e: Entry) -> str:
    return f"- {e.key}: {_one_line(e.content)}" if e.key else f"- {_one_line(e.content)}"


def render_block(memory: Memory, project: str, *, max_label: Label = Label.OWN_IP,
                 contributor_safe: bool = False, max_chars: int = 4000) -> str:
    """The marker block for `project`. Labels above OWN_IP are never included, whatever max_label says.

    contributor_safe also drops entries written by Claude or GPT (or an unknown model), for cards
    that may be placed in a Contributor request.
    """
    entries = memory.entries(project=project, max_label=min(max_label, Label.OWN_IP),
                             exclude_origins=NON_CONTRIBUTOR if contributor_safe else ())
    lines = [START, "## Compute Mint project card",
             "(generated from personal memory by `python -m compute_mint.project_card`; do not edit by hand)"]
    omitted = 0
    size = sum(len(x) + 1 for x in lines) + len(END) + 50     # room for the "more entries" line
    for kind in KINDS:
        group = [e for e in entries if e.kind == kind]
        if not group:
            continue
        section = ["", f"### {HEADINGS[kind]}"]
        for e in group:
            line = _line(e)
            if size + len(line) + 1 > max_chars:
                omitted += 1
                continue
            if section:
                lines += section
                size += sum(len(x) + 1 for x in section)
                section = []
            lines.append(line)
            size += len(line) + 1
    if omitted:
        lines.append(f"- (+{omitted} more entries in personal memory)")
    lines.append(END)
    return "\n".join(lines)


def apply_block(text: str, block: str) -> str:
    """`text` with its marker block replaced by `block` (appended if there is none)."""
    eol = "\r\n" if "\r\n" in text else "\n"
    block = block.replace("\n", eol)
    starts, ends = [m.start() for m in re.finditer(re.escape(START), text)], [m.start() for m in re.finditer(re.escape(END), text)]
    if not starts and not ends:
        if not text:
            return block + eol
        sep = "" if text.endswith(("\n", "\r\n")) else eol
        return text + sep + eol + block + eol
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise CardError("expected exactly one compute-mint start marker followed by one end marker")
    return text[:starts[0]] + block + text[ends[0] + len(END):]


def _read(p: Path) -> str:
    if not p.exists():
        return ""
    with open(p, encoding="utf-8", newline="") as f:      # newline="" keeps CRLF files intact
        return f.read()


def update_file(path: str | Path, block: str) -> bool:
    """Write the block into the file. Returns whether the file changed."""
    p = Path(path)
    old = _read(p)
    new = apply_block(old, block)
    if new == old:
        return False
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compute_mint.project_card", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", help="AGENTS.md / CLAUDE.md files to update (created if missing)")
    ap.add_argument("--project", required=True, help="project name used in memory")
    ap.add_argument("--db", default=None, help="memory SQLite path (default: $CM_MEMORY_PATH or data/memory.sqlite)")
    ap.add_argument("--max-label", choices=["public", "own_ip"], default="own_ip")
    ap.add_argument("--contributor-safe", action="store_true", help="leave out entries written by Claude/GPT")
    ap.add_argument("--max-chars", type=int, default=4000)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the block, write nothing")
    mode.add_argument("--check", action="store_true", help="exit 1 if any file is out of date, write nothing")
    args = ap.parse_args(argv)

    block = render_block(Memory(args.db or default_path()), args.project, max_label=Label[args.max_label.upper()],
                         contributor_safe=args.contributor_safe, max_chars=args.max_chars)
    if args.dry_run:
        print(block)
        return 0
    stale = 0
    for f in args.files:
        p = Path(f)
        try:
            if args.check:
                old = _read(p)
                changed = apply_block(old, block) != old
            else:
                changed = update_file(p, block)
        except CardError as e:
            print(f"{f}: {e}", file=sys.stderr)
            return 2
        stale += changed
        print(f"{f}: {'out of date' if args.check and changed else 'updated' if changed else 'unchanged'}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
