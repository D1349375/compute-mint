import json
import os
import shutil
import time
from pathlib import Path

from compute_mint.quota import BLOCK, codex_home, read_codex_quota

FIXTURES = Path(__file__).parent / "fixtures" / "codex_home"


def _home(tmp_path: Path, newest: str) -> Path:
    """Copy the fixture home into tmp_path with `newest` (a file name stem) as the most recently modified."""
    home = tmp_path / "codex-home"
    shutil.copytree(FIXTURES, home)
    now = time.time()
    rest = sorted((p for p in home.rglob("*.jsonl") if p.stem != newest), key=lambda p: p.name, reverse=True)
    for i, p in enumerate([p for p in home.rglob("*.jsonl") if p.stem == newest] + rest):
        os.utime(p, (now - i * 1000, now - i * 1000))
    return home


def test_reads_last_rate_limits_of_newest_session(tmp_path):
    home = _home(tmp_path, "rollout-2026-10-27T01-00-00-fixture-new")
    q = read_codex_quota(home)
    assert q["available"] and q["plan_type"] == "plus"
    assert q["primary"]["used_percent"] == 42.5 and q["primary"]["remaining_percent"] == 57.5
    assert q["primary"]["window_minutes"] == 300 and q["primary"]["resets_at"] == 1793100000
    assert q["secondary"]["used_percent"] == 61.0 and q["secondary"]["window_minutes"] == 10080
    assert q["primary"]["resets_at_iso"].startswith("2026-10-27T11:20:00")
    assert q["observed_at"] is not None


def test_output_carries_only_limits_never_session_content(tmp_path):
    out = json.dumps(read_codex_quota(_home(tmp_path, "rollout-2026-10-27T01-00-00-fixture-new")))
    for leak in ["FIXTURE-PROMPT-TEXT", "FIXTURE-REPLY-TEXT", "FIXTURE-AGENT-TEXT", "fixture-new", str(tmp_path)]:
        assert leak not in out


def test_falls_back_to_older_session_when_newest_has_no_rate_limits(tmp_path):
    q = read_codex_quota(_home(tmp_path, "rollout-2026-10-27T09-00-00-fixture-empty"))
    assert q["available"] and q["primary"]["used_percent"] == 42.5      # the newest session that has one


def test_only_the_old_session_present(tmp_path):
    home = _home(tmp_path, "x")
    for p in home.rglob("*fixture-new*"):
        p.unlink()
    for p in home.rglob("*fixture-empty*"):
        p.unlink()
    assert read_codex_quota(home)["primary"]["used_percent"] == 10.0


def test_missing_or_empty_home(tmp_path):
    assert read_codex_quota(tmp_path / "nope") == {"available": False, "reason": "no Codex session logs found"}
    (tmp_path / "sessions").mkdir()
    assert read_codex_quota(tmp_path)["available"] is False


def test_reads_from_the_end_of_a_large_log_and_is_read_only(tmp_path):
    day = tmp_path / "sessions" / "2026" / "10" / "27"
    day.mkdir(parents=True)
    log = day / "rollout-big.jsonl"
    limits = {"primary": {"used_percent": 7.0, "window_minutes": 300, "resets_at": 1793100000},
              "secondary": {"used_percent": 9.0, "window_minutes": 10080, "resets_at": 1793600000}, "plan_type": "pro"}
    filler = json.dumps({"type": "response_item", "payload": {"text": "x" * 500}})
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": None}}) + "\n")
        for _ in range(3 * BLOCK // 500):
            f.write(filler + "\n")
        f.write(json.dumps({"timestamp": "2026-10-27T02:00:00Z", "type": "event_msg",
                            "payload": {"type": "token_count", "rate_limits": limits}}) + "\n")
        for _ in range(2 * BLOCK // 500):
            f.write(filler + "\n")
    before = (log.read_bytes(), log.stat().st_mtime_ns)
    q = read_codex_quota(tmp_path)
    assert q["plan_type"] == "pro" and q["primary"]["used_percent"] == 7.0
    assert (log.read_bytes(), log.stat().st_mtime_ns) == before


def test_older_codex_versions_report_resets_in_seconds(tmp_path):
    day = tmp_path / "sessions" / "2026" / "10" / "27"
    day.mkdir(parents=True)
    rec = {"timestamp": "2026-10-27T00:00:00Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "primary": {"used_percent": 1.0, "window_minutes": 300, "resets_in_seconds": 600}}}}
    (day / "rollout-old.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    q = read_codex_quota(tmp_path)
    assert q["primary"]["resets_at"] == 1793059200.0 + 600 and q["secondary"] is None


def test_codex_home_defaults_and_env(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert codex_home() == Path("C:/codex-home")
    monkeypatch.setenv("CODEX_HOME", "D:/elsewhere")
    assert codex_home() == Path("D:/elsewhere")
