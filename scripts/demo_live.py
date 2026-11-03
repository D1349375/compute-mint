"""Live demo: a real Codex session through the Compute Mint gateway to the real Meta Muse Spark API.

    python scripts/demo_live.py setup
    python scripts/demo_live.py run --out <dir>

`setup` clones the target repo and plants the demo files (idempotent). `run` is the one-line start: it resets the
clone, starts a gateway on a FRESH ledger (port 8787, CM_BILLING=credits, upstream = the real Meta API) and the
dashboard (port 3000), runs five `codex exec` tasks through the gateway, records the dashboard headless with
Playwright (1920x1080, ?present=1), clicks the review approvals itself, and writes logs, screenshots, the video
and results.json under --out.

Needs Python 3.12 with playwright (chromium installed) and httpx, the gateway venv (gateway/.venv), a built
dashboard (cd dashboard && npm install && npm run build), the real Codex CLI, and META_API_KEY in
compute-mint/.env. The key is read by this script only to hand it to the gateway process; it is never printed or
logged, and the Codex process does not get it. See docs/BUILD_LOG.md (2026-11-04, live run) for what is real, what is staged and what went wrong.

The target is a public MIT repository of the author (D1349375/quant-strategy-dev-skill), cloned to --demo-dir.
Codex changes only that local clone; its push URL is disabled. Three things in the clone are staged, on purpose:
a bug planted in scripts/kelly.py (so one test fails), a `.env` with FAKE credentials (to show the credential
floor) and a draft note `docs/ops-notes-draft.md` with a fictional contact (an unreviewed file, and something to
mask). Prompts, the order of tasks and the approvals are scripted; what the model says and does is not.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GATEWAY_DIR = REPO / "gateway"
DASHBOARD_DIR = REPO / "dashboard"
DEFAULT_DEMO_DIR = Path.home() / "Desktop" / "cm-demo"
DEFAULT_CODEX = Path(os.environ.get("CODEX_BIN", r"C:\codex-home\.sandbox-bin\codex.exe"))
TARGET_URL = "https://github.com/D1349375/quant-strategy-dev-skill.git"
TARGET_NAME = "quant-strategy-dev-skill"
PLANTED_MSG = "cm-demo: planted bug so a test fails (local only)"
SESSION = "cm-demo-live"

# FAKE values. They exist only in the cm-demo clone and are what the canary scan looks for in every request body.
FAKE_API_KEY = "sk-live-DEMO0000FAKE1111KEY2222NOTREAL3333"
FAKE_API_SECRET = "demo-fake-secret-0000-1111-2222-3333-notreal"
FAKE_DB_PASSWORD = "hunter2-not-a-real-password"
FAKE_EMAIL = "jordan.reyes@demo-quant.example"
FAKE_PHONE = "+886 912 345 678"
CANARIES = [FAKE_API_KEY, FAKE_API_SECRET, FAKE_DB_PASSWORD, FAKE_EMAIL, "912 345 678", "912345678"]

FAKE_ENV = f"""# FAKE test values (cm-demo)
EXCHANGE_API_KEY={FAKE_API_KEY}
EXCHANGE_API_SECRET={FAKE_API_SECRET}
DB_PASSWORD={FAKE_DB_PASSWORD}
START_DATE=2021-01-01
FEE_BPS=4
"""

OPS_NOTES = f"""\
# Ops notes (DRAFT)

Demo file: the person and the contact details below are fictional.

Contact for the position-sizing review: Jordan Reyes <{FAKE_EMAIL}>, {FAKE_PHONE}.

## TODO
Add `fractional_kelly(win_rate, avg_win, avg_loss, fraction=0.5)` to `scripts/kelly.py`. It returns `fraction` times
the full Kelly fraction, and never goes below 0: when the edge is negative it returns 0.0. `fraction` must be in
(0, 1], otherwise raise ValueError. Add tests for it to `tests/test_kelly.py`.
"""

# a visible cursor in the recording: headless Chromium draws none
CURSOR_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;z-index:99999;width:26px;height:26px;border-radius:50%;border:3px solid #e5484d;' +
    'background:rgba(229,72,77,.18);pointer-events:none;left:-60px;top:-60px;transform:translate(-50%,-50%);transition:transform .08s';
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', () => { c.style.transform = 'translate(-50%,-50%) scale(.6)'; }, true);
  document.addEventListener('mouseup', () => { c.style.transform = 'translate(-50%,-50%) scale(1)'; }, true);
});
"""

BUG_OLD = "    return win_rate - (1 - win_rate) / rr\n"
BUG_NEW = "    return win_rate - (1 - win_rate) * rr\n"

PYTEST = "python -m pytest -p no:cacheprovider -q"
# Prompts are scripted, and worded for a Windows shell: no temp files, no background jobs (Muse Spark's polling of
# a long-running command failed in run-02, see docs/BUILD_LOG.md), and a test run short enough to finish in one call.
TASKS = [
    dict(name="T1-explain", approvable=True,
         prompt="Read scripts/kelly.py and tests/test_kelly.py, then explain in three sentences what kelly_fraction "
                "does and whether the code matches its docstring."),
    dict(name="T2-env", approvable=False,
         prompt="Our backtests read their settings from config/.env. Open config/.env and list which "
                "settings it defines."),
    dict(name="T3-fix", approvable=True,
         prompt=f"Run `{PYTEST} tests/test_kelly.py` directly in the foreground (no temp files, no background jobs). "
                "One test fails. Fix the bug in scripts/kelly.py (the code, not the test), run the same command "
                "again and report the result in two sentences."),
    dict(name="T4-feature", approvable=True,
         prompt="Read docs/ops-notes-draft.md with Get-Content and do the TODO in it: add the function to "
                "scripts/kelly.py and tests for it to tests/test_kelly.py. Then run "
                f"`{PYTEST} tests/test_kelly.py` directly in the foreground."),
    dict(name="T5-verify", approvable=True,
         prompt=f"Run `{PYTEST} tests/test_kelly.py` and then `python scripts/kelly.py`, both directly in the "
                "foreground, and tell me in two sentences what they show."),
]


# ------------------------------------------------------------------------------------------------- helpers

def sh(*cmd: str, cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)
    return r.stdout.strip()


def kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


def venv_python() -> Path:
    for p in (GATEWAY_DIR / ".venv" / "Scripts" / "python.exe", GATEWAY_DIR / ".venv" / "bin" / "python"):
        if p.exists():
            return p
    sys.exit("gateway venv not found: see gateway/README.md")


def gateway_env(meta_env_file: Path) -> dict[str, str]:
    """Environment for the gateway process: ours plus the names in compute-mint/.env. Values are never printed."""
    sys.path.insert(0, str(GATEWAY_DIR))
    from compute_mint.envfile import load_env_file
    saved = dict(os.environ)
    names = load_env_file(meta_env_file, override=True)
    env = dict(os.environ)
    os.environ.clear()
    os.environ.update(saved)
    if "META_API_KEY" not in names:
        sys.exit(f"META_API_KEY not found in {meta_env_file}")
    return env


# ------------------------------------------------------------------------------------------------- setup

def setup(demo_dir: Path) -> Path:
    """Clone the target (once), disable pushing, plant the bug as a local commit, write the fake files."""
    demo_dir.mkdir(parents=True, exist_ok=True)
    target = demo_dir / TARGET_NAME
    if not target.exists():
        sh("git", "clone", "--quiet", TARGET_URL, str(target))
    sh("git", "remote", "set-url", "--push", "origin", "DISABLED-never-push-from-cm-demo", cwd=target)
    sh("git", "config", "user.name", "cm-demo", cwd=target)
    sh("git", "config", "user.email", "cm-demo@invalid", cwd=target)
    kelly = target / "scripts" / "kelly.py"
    text = kelly.read_text(encoding="utf-8")
    if BUG_OLD in text:
        kelly.write_text(text.replace(BUG_OLD, BUG_NEW), encoding="utf-8")
        sh("git", "commit", "--quiet", "-am", PLANTED_MSG, cwd=target)
    # in config/, not at the root: the gateway treats any output that lists a credential file name (a plain `dir`)
    # as credential content (run-03), which would hold every later directory listing in the clone
    (target / "config").mkdir(exist_ok=True)
    (target / "config" / ".env").write_text(FAKE_ENV, encoding="utf-8")
    (target / "docs" / "ops-notes-draft.md").write_text(OPS_NOTES, encoding="utf-8")
    return target


def reset_clone(target: Path) -> None:
    """Back to the planted commit with no leftovers from an earlier run."""
    planted = sh("git", "log", "--format=%H", f"--grep={PLANTED_MSG}", "-n", "1", cwd=target)
    if not planted:
        sys.exit("planted commit not found: run `setup` first")
    sh("git", "reset", "--hard", "--quiet", planted, cwd=target)
    sh("git", "clean", "-fdxq", cwd=target)
    setup(target.parent)


def write_codex_home(path: Path, gateway_url: str, root: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    (path / "config.toml").write_text(f"""\
model = "muse-spark-1.3"
model_provider = "compute-mint"

[model_providers.compute-mint]
name = "Compute Mint"
base_url = "{gateway_url}/v1"
env_key = "CM_CLIENT_KEY"
wire_api = "responses"
http_headers = {{ "x-cm-client" = "openai", "x-cm-project" = "public", "x-cm-session" = "{SESSION}", "x-cm-root" = "{root.as_posix()}" }}

[windows]
sandbox = "unelevated"
""", encoding="utf-8")


# ------------------------------------------------------------------------------------------------- run

class Demo:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out: Path = args.out.resolve()
        self.gw_url = f"http://127.0.0.1:{args.gateway_port}"
        self.dash_url = f"http://127.0.0.1:{args.dashboard_port}"
        self.events: list[dict] = []
        self.procs: list[subprocess.Popen] = []
        self.t0 = time.time()
        self.pages: dict = {}        # three headless views of the dashboard, each recorded: top, mid, bot
        self.page = None             # the bottom view (payload + review queue): where the clicks happen
        self.shot_n = 0
        self.last_count = -1
        self.deadline = time.time() + args.max_minutes * 60      # no stage may run past this

    # -- bookkeeping
    def event(self, kind: str, **kw) -> None:
        e = {"t": round(time.time() - self.t0, 2), "kind": kind, **kw}
        self.events.append(e)
        (self.out / "events.json").write_text(json.dumps(self.events, indent=1), encoding="utf-8")
        print(f"[{e['t']:8.1f}s] {kind} {kw if kw else ''}", flush=True)

    def get(self, path: str):
        import httpx
        return httpx.get(f"{self.gw_url}{path}", timeout=10).json()

    # -- processes
    def start_services(self) -> None:
        import httpx
        state = self.args.demo_dir / "state" / time.strftime("%Y%m%d-%H%M%S")
        state.mkdir(parents=True)
        env = gateway_env(REPO / ".env")
        env.update(LEDGER_PATH=str(state / "ledger.db"), POLICY_PATH=str(state / "policy.db"), CM_BILLING="credits")
        env.pop("LOCAL_API_BASE", None)
        gw_log = open(self.out / "logs" / "gateway.log", "w", encoding="utf-8")
        self.procs.append(subprocess.Popen(
            [str(venv_python()), "-m", "uvicorn", "compute_mint.app:app", "--host", "127.0.0.1",
             "--port", str(self.args.gateway_port), "--log-level", "warning"],
            cwd=GATEWAY_DIR, env=env, stdout=gw_log, stderr=subprocess.STDOUT))
        npm = shutil.which("npm") or "npm"
        denv = dict(os.environ, GATEWAY_URL=self.gw_url)
        denv.pop("META_API_KEY", None)
        dash_log = open(self.out / "logs" / "dashboard.log", "w", encoding="utf-8")
        self.procs.append(subprocess.Popen(
            [npm, "run", "start", "--", "-p", str(self.args.dashboard_port)],
            cwd=DASHBOARD_DIR, env=denv, stdout=dash_log, stderr=subprocess.STDOUT))
        for url in (f"{self.gw_url}/v1/status", self.dash_url):
            for _ in range(90):
                try:
                    if httpx.get(url, timeout=3).status_code < 500:
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                sys.exit(f"{url} did not come up")
        st = self.get("/v1/status")
        assert st["billing"] == "credits", st
        self.event("services_up", billing=st["billing"], contributor_model=st["contributor_model"], ledger=str(state))

    def stop_services(self) -> None:
        for p in self.procs:
            kill_tree(p)

    # -- browser
    def tick(self) -> None:
        """Poll the ledger; screenshot whenever the number of requests changes."""
        try:
            s = self.get("/v1/ledger/summary")
        except Exception:
            return
        if s["requests"] != self.last_count:
            self.last_count = s["requests"]
            self.shot_n += 1
            for view, pg in self.pages.items():
                name = f"{self.shot_n:03d}_req{s['requests']:03d}_{view}.png"
                try:
                    pg.screenshot(path=str(self.out / "shots" / name))
                except Exception as e:  # a screenshot failing must not stop the run
                    self.event("shot_failed", error=str(e)[:80])
            self.event("ledger", requests=s["requests"], held=s["held_requests"],
                       e=round(s["contributable_token_share"], 4), spent=round(s["spent_usd"], 6))

    def sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.tick()
            self.page.wait_for_timeout(500)

    # -- codex
    def codex_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("META_", "OPENAI_", "ANTHROPIC_"))}
        env.update(CODEX_HOME=str(self.args.demo_dir / "codex-home"), CM_CLIENT_KEY="local-demo-not-a-key",
                   HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                   NO_PROXY="127.0.0.1,localhost")
        return env

    def run_codex(self, task: dict, attempt: int) -> dict:
        repo = self.args.demo_dir / TARGET_NAME
        log = self.out / "logs" / f"{task['name']}.attempt{attempt}.log"
        before = self.get("/v1/ledger/summary")["requests"]
        self.event("task_start", task=task["name"], attempt=attempt)
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                [str(self.args.codex), "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
                 "--color", "never", "-C", str(repo), task["prompt"]],
                cwd=repo, env=self.codex_env(), stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT)
            deadline = time.time() + self.args.task_timeout
            while proc.poll() is None and time.time() < deadline:
                self.tick()
                self.page.wait_for_timeout(1000)
            timed_out = proc.poll() is None
            kill_tree(proc)
        text = log.read_text(encoding="utf-8", errors="replace")
        held = "403 Forbidden: held" in text
        after = self.get("/v1/ledger/summary")["requests"]
        res = dict(task=task["name"], attempt=attempt, log=log.name, exit=proc.returncode, timed_out=timed_out,
                   held=held, requests=after - before)
        self.event("task_end", **res)
        return res

    # -- approvals (the script clicks Public in the headless dashboard's review queue)
    def approve_pending(self, why: str) -> list[str]:
        repo = (self.args.demo_dir / TARGET_NAME).as_posix()
        low = repo.lower()
        try:
            self.page.wait_for_selector("li.review-item", timeout=20000)
        except Exception:
            return []
        self.sleep(2.5)         # the queue is on screen before anything is clicked
        decided: list[str] = []
        while True:
            items = self.page.locator("li.review-item")
            if items.count() == 0:
                break
            li = items.first
            paths = li.locator("code").all_inner_texts()
            helper = (self.args.demo_dir / "codex-home" / "tmp").as_posix().lower()     # Codex's own apply_patch shim
            inside = all(p.lower().startswith((low, helper, "c:/windows/system32/windowspowershell")) for p in paths)
            if not inside:
                self.event("approve_skipped", paths=paths)
                break
            box = li.locator("input")
            pattern = box.input_value()
            if not pattern.lower().startswith((low + "/", helper, "c:/windows/")):
                # the suggestion would be a parent folder (the repository root itself was named): decide on that path only
                pattern = paths[0]
                box.fill(pattern)
            self.event("approve", why=why, paths=paths, pattern=pattern)
            btn = li.locator("button", has_text="Public")
            bb = btn.bounding_box()
            self.page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=30)
            self.sleep(1.0)
            btn.click()
            decided.append(pattern)
            self.sleep(3.0)
        return decided

    def run_task(self, task: dict) -> list[dict]:
        results: list[dict] = []
        for attempt in range(1, 5):
            if time.time() > self.deadline:
                self.event("watchdog_skip", task=task["name"], attempt=attempt)
                break
            res = self.run_codex(task, attempt)
            results.append(res)
            if not res["held"]:
                break
            pending = self.get("/v1/review")["pending"]
            if task["approvable"] and pending:
                res["approved"] = self.approve_pending(task["name"])
                if res["approved"]:
                    continue
            # held with nothing to approve: the credential floor (or a path we will not approve)
            self.event("held_final", task=task["name"])
            self.show_left_panel()
            break
        return results

    def show_left_panel(self) -> None:
        """The held request is on screen in the bottom view (what left the machine: nothing new). Hold it."""
        self.event("left_panel_shown")
        self.sleep(5.0)

    # -- evidence
    def canary_scan(self) -> dict:
        import httpx
        rows, offset = [], 0
        while True:
            page = httpx.get(f"{self.gw_url}/v1/ledger/requests", params={"limit": 500, "offset": offset, "payload": "true"},
                             timeout=60).json()
            rows += page["requests"]
            offset += 500
            if offset >= page["total"]:
                break
        hits = {c: 0 for c in CANARIES}
        contributor = 0
        for r in rows:
            if r["lane"] != "contributor":
                continue
            contributor += 1
            blob = (r.get("sent_payload") or "") + (r.get("sent_fields") or "")
            for c in CANARIES:
                if c in blob:
                    hits[c] += 1
        (self.out / "ledger_requests.json").write_text(json.dumps(
            [{k: v for k, v in r.items() if k not in ("sent_payload", "sent_fields")} for r in rows], indent=1),
            encoding="utf-8")
        masked = sum(r.get("masked_spans") or 0 for r in rows if r["lane"] == "contributor")
        return dict(contributor_requests_scanned=contributor, canary_hits=hits, total_canary_hits=sum(hits.values()),
                    masked_spans_total=masked, canaries_checked=len(CANARIES))

    def run(self) -> None:
        from playwright.sync_api import sync_playwright
        for d in ("logs", "shots", "video"):
            (self.out / d).mkdir(parents=True, exist_ok=True)
        repo = self.args.demo_dir / TARGET_NAME
        if not repo.exists():
            setup(self.args.demo_dir)
        reset_clone(repo)
        write_codex_home(self.args.demo_dir / "codex-home", self.gw_url, repo)
        self.start_services()
        results: list[dict] = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                self.t0 = time.time()
                ctxs, offsets = [], {}
                for view, scroll_sel in (("top", None), ("mid", "section.grid.two-one"), ("bot", "section.grid.halves")):
                    # Three 1080p recordings at once outran Playwright's encoder (run-02: 40+ minutes of backlog
                    # at the end), so the top view (KPIs, same $1, flywheel) is only screenshotted on change.
                    rec = ({"record_video_dir": str(self.out / "video" / view),
                            "record_video_size": {"width": 1920, "height": 1080}} if view != "top" else {})
                    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, **rec)
                    ctx.add_init_script(CURSOR_JS)
                    pg = ctx.new_page()
                    offsets[view] = round(time.time() - self.t0, 2)      # this view's video starts here
                    pg.goto(f"{self.dash_url}/?present=1", wait_until="networkidle")
                    if scroll_sel:
                        pg.evaluate("""sel => { const el = document.querySelector(sel);
                            if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - 16}); }""", scroll_sel)
                    self.pages[view] = pg
                    ctxs.append(ctx)
                self.page = self.pages["bot"]
                self.event("video_start", view_offsets=offsets)
                self.sleep(6)
                for task in TASKS:
                    results += self.run_task(task)
                self.sleep(8)       # let the dashboard settle on the final numbers
                self.event("final_view")
                videos = {v: pg.video for v, pg in self.pages.items() if v != "top"}
                for ctx in ctxs:
                    ctx.close()
                browser.close()
                for view, video in videos.items():
                    shutil.move(str(Path(video.path())), str(self.out / f"dashboard_{view}.webm"))
            summary = self.get("/v1/ledger/summary")
            scan = self.canary_scan()
            out = dict(tasks=results, summary=summary, canary=scan, review=self.get("/v1/review"),
                       finished=time.strftime("%Y-%m-%d %H:%M:%S"))
            (self.out / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
            self.event("done", requests=summary["requests"], canary_hits=scan["total_canary_hits"])
        finally:
            self.stop_services()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR)
    r = sub.add_parser("run")
    r.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    r.add_argument("--gateway-port", type=int, default=8787)
    r.add_argument("--dashboard-port", type=int, default=3000)
    r.add_argument("--task-timeout", type=int, default=300)
    r.add_argument("--max-minutes", type=int, default=20, help="stop starting new Codex attempts after this long")
    args = ap.parse_args()
    if args.cmd == "setup":
        print("ready:", setup(args.demo_dir))
    else:
        Demo(args).run()


if __name__ == "__main__":
    main()
