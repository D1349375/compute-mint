# gateway

OpenAI-compatible proxy that routes each request to Muse Spark Contributor or Standard.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn compute_mint.app:app --port 8787
```

Point an agent at `http://localhost:8787/v1`. Per-request headers:

| Header | Values | Meaning |
|---|---|---|
| `x-cm-session` | any id | groups requests for masking and provenance |
| `x-cm-project` | `public`, `own_ip`, `confidential` | baseline label of this project's content |
| `x-cm-dial` | `public`, `own_ip` | strictest label the user agrees to contribute |
| `x-cm-client` | `anthropic`, `openai`, `unknown` | model behind the calling agent; labels the agent's own assistant messages with that origin |

`GET /v1/ledger/summary` returns spend, counterfactual spend, savings and the contributable token share.

| Module | Role |
|---|---|
| `labels.py` | PUBLIC < OWN_IP < CONFIDENTIAL < FLOOR; the dial can never reach CONFIDENTIAL or FLOOR |
| `origin.py` | who produced content (USER, TOOL, PUBLIC_SOURCE, META, LOCAL_MODEL, ANTHROPIC, OPENAI, UNKNOWN_MODEL); Claude, GPT and unidentified-model output never goes to Contributor |
| `detect.py` | deterministic credential / personal-data detectors |
| `vault.py` | session-consistent placeholders and rehydration |
| `context.py` | taint tracking; provenance of gateway-generated replies |
| `router.py` | lane decision and clean-context assembly |
| `pricing.py`, `ledger.py` | official prices and the counterfactual ledger |
| `app.py` | the proxy |
| `memory.py` | personal memory in SQLite (preferences, project facts, accepted plans), each with origin and label |
| `delegate.py`, `sources.py` | `delegate`: fixed task templates over sources the gateway fetches itself |
| `mcp_server.py` | MCP server (stdio): `delegate`, `recall`, `quota` |
| `quota.py` | read-only Codex `rate_limits` from local session logs |
| `project_card.py` | generated block in `AGENTS.md` / `CLAUDE.md` from memory |

## Origin: which content may go to Contributor

Contributor needs **both** a label that fits the dial **and** an allowed origin. Anthropic's and OpenAI's terms
forbid using their models' outputs to train competing models, and Contributor traffic is used by Meta for
training, so content written by those models (or by a model we cannot identify) never goes to Contributor, however
public it is.

| Message | Origin |
|---|---|
| `user`, `system` | `USER` |
| `tool` | `TOOL` |
| `assistant`, produced by the gateway (found in provenance) | `META` |
| `assistant`, anything else | the model declared in `x-cm-client`, otherwise `UNKNOWN_MODEL` |
| gateway reply generated from a context that held any of the above foreign origins | that foreign origin (it derives from it) |

A request is a Contributor request only if no message has an origin in `ANTHROPIC`, `OPENAI`, `UNKNOWN_MODEL`.
In practice an agent's own history (its assistant turns) keeps those requests on Standard; fresh,
self-contained requests (such as `delegate`) are the ones that go to Contributor. `x-cm-client` can only name a
foreign model, so it cannot loosen anything. Limits: a user or tool message that pastes model output is
indistinguishable from user text and is labeled `USER`/`TOOL`.

## MCP server

```bash
claude mcp add compute-mint -- <repo>/gateway/.venv/Scripts/python -m compute_mint.mcp_server   # Claude Code
```

For Codex, add to `config.toml`:

```toml
[mcp_servers.compute-mint]
command = "<repo>/gateway/.venv/Scripts/python.exe"
args = ["-m", "compute_mint.mcp_server"]
```

Environment: `META_API_KEY`, `META_API_BASE`, `CONTRIBUTOR_MODEL`, `STANDARD_MODEL`, `LEDGER_PATH` (as the gateway),
`CM_PUBLIC_ROOT` (the only folder `delegate` may read), `CM_CALLER_ORIGIN` (`anthropic`, `openai` or
`unknown_model`: the model driving the agent), `CM_MEMORY_PATH` or `CM_DATA_DIR` (memory database), `CODEX_HOME`.

| Tool | |
|---|---|
| `delegate(task_type, refs, instruction=None)` | `task_type` is `summarize`, `extract`, `explain_error` or `search`. `refs` are public http(s) URLs, files under `CM_PUBLIC_ROOT`, or (search only) query strings. The gateway fetches the text, applies its own template and routes it. Reference strings are not copied into the prompt. Free-text `instruction` carries the caller's origin, so that request goes to Standard only. |
| `recall(query, project=None, limit=5)` | keyword search of personal memory; labels above CONFIDENTIAL (credentials, personal data) are never returned |
| `quota()` | Codex 5-hour and weekly limits |

Fetching only follows public URLs: http(s), no userinfo, every resolved address public (re-checked on each
redirect), text content only, size capped. No search backend is configured by default (`search` needs
`PublicFetcher(search_fn=...)`).

## Memory and project card

```bash
.venv/Scripts/python -m compute_mint.memory add preference "Reply in Traditional Chinese" --key language
.venv/Scripts/python -m compute_mint.memory add project_fact "Gateway runs on port 8787" --project my-repo --key port
.venv/Scripts/python -m compute_mint.project_card --project my-repo AGENTS.md CLAUDE.md   # --dry-run / --check available
```

Content that contains credentials or personal data is stored with label FLOOR and is never returned or put in a
card. The card holds only entries up to OWN_IP, in a stable order without timestamps, and only touches the text
between `<!-- compute-mint:start -->` and `<!-- compute-mint:end -->` (appended if missing; damaged markers abort
without writing). Run it between sessions, not during one, so the prompt prefix stays cached.

## Codex quota

`quota.py` opens `$CODEX_HOME/sessions/**/*.jsonl` (default `C:/codex-home`) read-only, takes the last
`event_msg`/`token_count` record with `rate_limits` from the newest session that has one, and returns
`primary`/`secondary` (`used_percent`, `remaining_percent`, `window_minutes`, `resets_at`) and `plan_type`.
It never returns prompts, replies or file paths. `python -m compute_mint.quota` prints the current values.
