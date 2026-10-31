"""File paths named in free text: tool output (tracebacks, test runners, grep, compilers) and shell commands.

A tool output that was not read from one named file (a test run, a shell command) says nothing about
its own sensitivity, but the paths it prints do: a traceback through `config/secrets.py` or a grep
hit in `contracts/acme.md` points at where the text came from. This module only finds the paths;
`policy.py` decides what they are worth.

Recognized: Python `File "x", line N`, `path:line[:col]`, pytest `path::test`, compiler and linter
output (`./x.go:12:3`, `--> src/a.rs:3:5`, `src/a.ts(12,5)`), absolute POSIX and Windows paths, `./` and
`../` paths, any `dir/file.ext`, git diff headers, `--opt=path`. Chinese, Japanese and Korean text has no
spaces, so a path may be glued to the words around it (`錯誤在config/a.py:3行`). Not recognized: paths that
contain spaces (except inside `File "..."`) and a bare directory name without a slash.
"""
import posixpath
import re
from dataclasses import dataclass

from .cjk import SCRIPTS
from .detect import half_width

_URL = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+")
_FILE_QUOTED = re.compile(r"""\bFile\s+(["'])(?P<p>.+?)\1""")
_DIFF = re.compile(r"(?m)^(?:diff --git a/(?P<a>\S+) b/(?P<b>\S+)|(?:---|\+\+\+) [ab]/(?P<c>\S+))")
_SPLIT = re.compile(r"""[\s"'<>|*?()\[\]{},;`\u3000-\u303f]+""")
_HAS_SCRIPT = re.compile(f"[{SCRIPTS}]")
_GLUED_TAIL = re.compile(rf"^(.*?(?:\.[A-Za-z][A-Za-z0-9]{{0,9}}|:\d+)):?[{SCRIPTS}].*$", re.S)
_GLUED_HEAD = re.compile(rf"^[{SCRIPTS}]+:?(?=[A-Za-z0-9_.~/\\-])")
_ROOTED_DEEP = re.compile(r"^[/\\][^/\\]+[/\\]")
_LINE_SUFFIX = re.compile(r"(?::\d+)+(?::.*)?$")
_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,9}$")
_WIN_ABS = re.compile(r"^[A-Za-z]:/")

# Library code is public by nature and would flood the review queue.
_LIBRARY_MARKERS = ("/site-packages/", "/dist-packages/", "/node_modules/", "/lib/python3", "/lib64/python3",
                    "/.cargo/registry/", "/go/pkg/mod/", "/usr/lib/", "/usr/local/lib/", "/usr/share/")

_ROOT_HINT = re.compile(
    r"(?i)(?:working[ _-]?dir(?:ectory)?|current[ _-]?(?:working[ _-]?)?dir(?:ectory)?|(?:project|repository|repo|workspace)[ _-]?(?:root|dir(?:ectory)?|folder)|\bcwd\b)"
    r"""[^\n/\\A-Za-z0-9~]{0,24}?(?:is|:|=|>)?[ \t"'`>]*"""
    r"""(?P<root>/[\w.@+%=-]+(?:/[\w.@+%=-]+)*|[A-Za-z]:[\\/][^\s"'<>|*?`]+)""")


@dataclass(frozen=True)
class PathRef:
    path: str            # forward slashes, `.`/`..` collapsed where possible
    absolute: bool
    dirless: bool        # a bare file name such as `main.py:12`: only usable if the name is already known
    library: bool = False


def is_absolute(path: str) -> bool:
    return path.startswith("/") or path.startswith("~/") or bool(_WIN_ABS.match(path))


_FILE_EXTS = frozenset("""py pyi js jsx mjs cjs ts tsx json yaml yml toml ini cfg conf md rst txt csv tsv log env sh bash ps1 bat sql
xml html htm css scss java kt go rs rb php c h cc cpp hpp cs swift lock pem key crt cer p12 pfx kdbx properties
ipynb gradle tf tfvars parquet db sqlite sqlite3 jsonl ndjson zip tar gz tgz xlsx xls docx pdf png jpg jpeg svg proto graphql
vue svelte dart scala lua pl r m ex exs erl hs ml clj nix""".split())


def _classify(token: str, command: bool) -> PathRef | None:
    node = "::" in token
    t = token.split("::")[0] if node else token
    if not t or "://" in t or t.startswith("//") or (t.startswith("-") and "=" not in t):
        return None
    if "=" in t:
        t = t.rsplit("=", 1)[1]
    t = t.rstrip(".,;:!?")
    had_line = bool(_LINE_SUFFIX.search(t))     # path:12  path:12:5  grep's path:12:text
    t = _LINE_SUFFIX.sub("", t).rstrip(".,;:!?")
    if not t or ("@" in t and "/" not in t):
        return None
    if t.startswith("\\") and not t.startswith("\\\\"):
        return None     # an escape sequence inside a repr (backslash-n and the like), not a rooted Windows path
    t = t.replace("\\", "/")
    if t in {".", "..", "/", "~"}:
        return None
    absolute = is_absolute(t)
    parts = [p for p in t.split("/") if p]
    if any(part in {"n", "r", "t"} for part in parts):
        return None
    base = parts[-1] if parts else ""
    ext = _EXT.search(base)
    stem_ok = bool(re.search(r"[^\W\d]", base.split(".")[0])) or base.startswith(".")
    if absolute:
        if not (len(parts) >= 2 or ext):
            return None
    elif t.startswith("./") or t.startswith("../"):
        if len(parts) < 2:
            return None
    elif "/" in t:
        if not (ext and stem_ok and ext.group(0)[1:].lower() in _FILE_EXTS):
            return None
    else:
        # a file in the working directory: `main.py:12`, `tests.py::t`, or a word of a shell command
        dotfile = base.startswith(".") and len(base) > 1 and base[1:2].isalpha()
        known = bool(ext) and ext.group(0)[1:].lower() in _FILE_EXTS and stem_ok
        if not (known or dotfile) or not (command or had_line or node):
            return None
        return PathRef(t, False, True)
    norm = posixpath.normpath(t)
    library = any(m in "/" + norm.lstrip("/") + "/" for m in _LIBRARY_MARKERS)
    return PathRef(norm, absolute, False, library)


def _unglue(token: str) -> str:
    """The path in a token that also holds the words around it. A leading run followed by a slash is a directory
    (`資料/客戶.csv`) unless what follows is clearly rooted (`在/work/shop/a.py`)."""
    if not _HAS_SCRIPT.search(token):
        return token
    tail = _GLUED_TAIL.match(token)
    if tail:
        token = tail.group(1)
    head = _GLUED_HEAD.match(token)
    if head:
        rest = token[head.end():]
        if not rest.startswith(("/", "\\")) or _ROOTED_DEEP.match(rest):
            return rest
    return token


def paths_in_text(text: str, command: bool = False) -> list[PathRef]:
    """Paths named in `text`, in order of first appearance, without duplicates."""
    if not isinstance(text, str) or not text:
        return []
    text = half_width(text)
    out: dict[str, PathRef] = {}

    def add(ref: PathRef | None) -> None:
        if ref is not None and ref.path not in out:
            out[ref.path] = ref

    for m in _FILE_QUOTED.finditer(text):
        p = m.group("p").strip()
        if p and not p.startswith("<"):
            ref = _classify(p, True)
            add(ref if ref is not None else _quoted_fallback(p))
    for m in _DIFF.finditer(text):
        for g in ("a", "b", "c"):
            if m.group(g):
                add(_classify(m.group(g), True))
    scrubbed = _URL.sub(" ", _DIFF.sub(" ", _FILE_QUOTED.sub(" ", text)))
    for token in _SPLIT.split(scrubbed):
        add(_classify(_unglue(token), command))
    return list(out.values())


def _quoted_fallback(p: str) -> PathRef | None:
    """`File "x"` is explicit even when `x` has no extension or directory."""
    p = p.replace("\\", "/")
    if "/" not in p and not _EXT.search(p):
        return PathRef(p, False, True)
    return None


def resolve(ref: PathRef, base: str | None) -> str | None:
    """Absolute path for `ref`, joining relative paths onto `base`; None if that is not possible."""
    if ref.absolute:
        return ref.path
    if not base:
        return None
    return posixpath.normpath(base.rstrip("/") + "/" + ref.path)


def root_from_text(text: str) -> str | None:
    """A working-directory statement such as `Primary working directory: /w/x`, `<cwd>/w/x</cwd>`,
    `The repository root is /w/x.`"""
    m = _ROOT_HINT.search(text or "")
    if m is None:
        return None
    root = m.group("root").replace("\\", "/").rstrip(".,;:)'\"`")
    return posixpath.normpath(root) if len(root) > 1 else None
