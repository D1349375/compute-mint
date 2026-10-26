"""The agent's tools, executed on a throw-away copy of a synthetic repository.

list_files(directory), read_file(path), write_file(path, content), run_tests(target).

Argument names matter to the gateway: its path rules look at arguments called `path`,
`file_path`, `cwd`, ... so `read_file` and `write_file` carry a `path` (their output is labeled
by what the owner said about that file), while `list_files` takes a `directory` and `run_tests`
a `target`, which the gateway does not treat as file paths. That mirrors a coding agent whose
shell tool output is not tied to one file.
"""
import hashlib
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT_CHARS = 12000
_SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git"}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List the files under a directory of the repository (recursive), with sizes.",
        "parameters": {"type": "object", "properties": {
            "directory": {"type": "string", "description": "Absolute path of a directory under the repository root."}}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Return the full text of a file.",
        "parameters": {"type": "object", "required": ["path"], "properties": {
            "path": {"type": "string", "description": "Absolute path of a file under the repository root."}}}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content.",
        "parameters": {"type": "object", "required": ["path", "content"], "properties": {
            "path": {"type": "string", "description": "Absolute path of a file under the repository root."},
            "content": {"type": "string", "description": "The complete new content of the file."}}}}},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Run pytest in the repository root and return its output.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Optional pytest arguments, e.g. 'tests/test_x.py'."}}}}},
]

_PYTEST_MEMO: dict[str, tuple[int, str]] = {}


def _skip(rel_parts: tuple[str, ...]) -> bool:
    return any(part in _SKIP_PARTS for part in rel_parts)


def tree_hash(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not _skip(rel.parts):
            h.update(rel.as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _normalize_output(text: str, root: Path) -> str:
    """Make pytest output identical across runs and platforms."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for variant in {str(root), str(root).replace("\\", "/"), str(root.resolve()), str(root.resolve()).replace("\\", "/")}:
        text = text.replace(variant, ".")
    text = re.sub(r"[A-Za-z]:[\\/][^\s'\"]*?pytest-of-[^\s'\"]*", "<tmp>", text)
    text = re.sub(r"/[^\s'\"]*?pytest-of-[^\s'\"]*", "<tmp>", text)
    # Windows prints tracebacks with backslashes: tests\test_x.py -> tests/test_x.py
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(?<=[\w.])\\(?=[\w.]+(?:\\[\w.]+)*\.py\b)", "/", text)
    text = re.sub(r" in \d+(?:\.\d+)?s\b", " in Xs", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n") + "\n"


def run_pytest(root: Path, args: list[str]) -> tuple[int, str]:
    """Run pytest in `root` (memoized on the repository content and arguments). Returns
    (exit code, normalized output). The child gets a minimal environment so nothing from the
    caller's shell can reach (or change) a test run."""
    key = tree_hash(root) + "|" + " ".join(args)
    if key in _PYTEST_MEMO:
        return _PYTEST_MEMO[key]
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE")
           if k in os.environ}
    env.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore", *args]
    try:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, timeout=180)
        code, raw = proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, raw = 124, "pytest timed out"
    result = (code, _normalize_output(raw, root))
    _PYTEST_MEMO[key] = result
    return result


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return text[:half] + f"\n[output truncated: {len(text) - MAX_OUTPUT_CHARS} chars omitted]\n" + text[-half:]


def mount_for(repo: str) -> str:
    """Where the repository appears to the agent. Tool paths are absolute (like real coding agents), so
    path rules learned for one repository can never match a file of another."""
    return f"/work/{repo}"


class Workspace:
    def __init__(self, root: Path, mount: str = "/work/repo") -> None:
        self.root = Path(root)
        self.mount = mount.rstrip("/")

    def _resolve(self, rel: str) -> Path | None:
        text = str(rel).replace("\\", "/").strip() or "."
        if text == self.mount:
            text = "."
        elif text.startswith(self.mount + "/"):
            text = text[len(self.mount) + 1:]
        norm = posixpath.normpath(text)
        if norm.startswith("/") or norm == ".." or norm.startswith("../") or re.match(r"^[A-Za-z]:", norm):
            return None
        return self.root / norm

    def list_files(self, directory: str = ".") -> str:
        base = self._resolve(directory)
        if base is None or not base.is_dir():
            return f"error: no such directory: {directory}"
        lines = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not _skip(rel.parts):
                lines.append(f"{self.mount}/{rel.as_posix()}  ({p.stat().st_size} bytes)")
        return "\n".join(lines) + "\n" if lines else "(empty)\n"

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if p is None or not p.is_file():
            return f"error: no such file: {path}"
        return p.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        if p is None:
            return f"error: path outside the repository: {path}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        return f"wrote {len(content.encode('utf-8'))} bytes to {path}"

    def run_tests(self, target: str = "") -> str:
        code, out = run_pytest(self.root, target.split() if target.strip() else [])
        return _cap(out) + f"[exit code: {code}]\n"

    def execute(self, name: str, arguments: dict) -> str:
        try:
            if name == "list_files":
                return self.list_files(arguments.get("directory", "."))
            if name == "read_file":
                return self.read_file(arguments["path"])
            if name == "write_file":
                return self.write_file(arguments["path"], arguments["content"])
            if name == "run_tests":
                return self.run_tests(arguments.get("target", ""))
        except KeyError as e:
            return f"error: missing argument {e}"
        return f"error: unknown tool {name}"
