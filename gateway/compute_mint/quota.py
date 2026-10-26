"""Read-only view of the Codex CLI rate limits.

Codex writes a rollout log (jsonl) per session under $CODEX_HOME/sessions. Each
`event_msg` / `token_count` record carries the account's current `rate_limits`. This module
opens those files read-only, looks at the newest session that has such a record, and returns
only the rate-limit numbers and the plan type. It never returns or logs prompts, replies or
paths, and it needs no token or login.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CODEX_HOME = "C:/codex-home"
MAX_FILES = 5            # newest sessions to look through if the latest has no rate_limits yet
BLOCK = 64 * 1024


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or DEFAULT_CODEX_HOME)


def _lines_reversed(path: Path):
    """Yield the file's lines from the end, reading it backwards in blocks."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        tail = b""
        while pos > 0:
            step = min(BLOCK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step) + tail
            lines = chunk.split(b"\n")
            tail = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    yield line
        if tail.strip():
            yield tail


def _window(w: object, observed: float | None) -> dict | None:
    if not isinstance(w, dict) or not isinstance(w.get("used_percent"), (int, float)):
        return None
    resets_at = w.get("resets_at")
    if resets_at is None and isinstance(w.get("resets_in_seconds"), (int, float)) and observed is not None:
        resets_at = observed + w["resets_in_seconds"]       # older Codex versions
    out = {"used_percent": float(w["used_percent"]),
           "remaining_percent": max(0.0, 100.0 - float(w["used_percent"])),
           "window_minutes": w.get("window_minutes"), "resets_at": resets_at}
    if isinstance(resets_at, (int, float)):
        out["resets_at_iso"] = datetime.fromtimestamp(resets_at, timezone.utc).isoformat()
    return out


def _parse_ts(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _latest_rate_limits(path: Path) -> dict | None:
    for raw in _lines_reversed(path):
        if b"token_count" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        payload = rec.get("payload") if isinstance(rec, dict) else None
        if rec.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        limits = payload.get("rate_limits")
        if not isinstance(limits, dict):
            continue
        observed = _parse_ts(rec.get("timestamp"))
        primary, secondary = _window(limits.get("primary"), observed), _window(limits.get("secondary"), observed)
        if primary is None and secondary is None:
            continue
        return {"available": True, "plan_type": limits.get("plan_type"), "primary": primary,
                "secondary": secondary, "observed_at": observed}
    return None


def read_codex_quota(home: str | Path | None = None) -> dict:
    """Newest rate limits found under `home/sessions`, or {"available": False, "reason": ...}."""
    root = Path(home) if home else codex_home()
    try:
        files = sorted((p for p in (root / "sessions").rglob("*.jsonl") if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        files = []
    if not files:
        return {"available": False, "reason": "no Codex session logs found"}
    for path in files[:MAX_FILES]:
        try:
            found = _latest_rate_limits(path)
        except OSError:
            continue
        if found:
            return found
    return {"available": False, "reason": "no rate_limits in the newest Codex sessions"}


if __name__ == "__main__":
    print(json.dumps(read_codex_quota(), indent=2))
