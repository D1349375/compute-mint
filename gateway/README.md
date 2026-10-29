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
| `x-cm-root` | absolute path | the agent's working directory; places the relative paths printed in tool output. Optional: the system prompt (or first user message) is searched for `working directory: …`, `repository root is …`, `<cwd>…</cwd>`, and a tool call's own `cwd`/`workdir` argument wins |

`GET /v1/ledger/summary` returns spend, counterfactual spend, savings, the contributable token share, the cache hit rate, the Context Broker's context ratio, held and local request counts, and the spend paid with credits.

## Billing mode

| `CM_BILLING` | A request that may not go to Contributor goes to |
|---|---|
| `paid` | Standard (`STANDARD_MODEL`). Paid use is not used for training (ToS §5.1) |
| `credits` (default) | the local model at `LOCAL_API_BASE` (`LOCAL_MODEL`, default `muse-glimmer`) if set, otherwise nowhere: the gateway answers 403 with lane `held` |

Use paid with promotional credits, hackathon credits included, counts as non-paid (ToS §13.3), and under §6 every non-paid request may be used for training and must not carry sensitive, confidential or personal information (§6.2), on Standard models as well. So on credits the only Meta requests are clean Contributor requests. Agent-authored history (Claude, GPT) is held for the same reason. Every response carries `x-cm-billing`; set `CM_BILLING=paid` only when the account pays for its usage.

`GET /v1/review` lists files waiting for a sensitivity decision and the learned rules; `POST /v1/review/{id}` with `{"label": "public|own_ip|confidential", "pattern": "<optional glob>"}` turns a decision into a rule. Files with no rule are treated as confidential until reviewed; credential files (`.env`, keys, `auth.json`, …) are always FLOOR.

| Module | Role |
|---|---|
| `labels.py` | PUBLIC < OWN_IP < CONFIDENTIAL < FLOOR; the dial can never reach CONFIDENTIAL or FLOOR |
| `origin.py` | who produced content (USER, TOOL, PUBLIC_SOURCE, META, LOCAL_MODEL, ANTHROPIC, OPENAI, UNKNOWN_MODEL); Claude, GPT and unidentified-model output never goes to Contributor |
| `detect.py` | deterministic credential / personal-data detectors |
| `vault.py` | session-consistent placeholders and rehydration |
| `context.py` | taint tracking; provenance of gateway-generated replies |
| `router.py` | lane decision and clean-context assembly |
| `broker.py` | cache-aware Context Broker: compacts aged tool outputs once, memoized, so the cached prefix keeps matching |
| `policy.py` | learned path rules and the review queue; credential files are always FLOOR; labels tool output that names no file (below) |
| `outpaths.py` | file paths in free text: tracebacks, `path:line`, pytest ids, compiler output, shell commands |
| `fingerprint.py` | content fingerprints of sensitive text read earlier (in-memory, keyed hashes) |
| `billing.py` | paid vs credits: where non-contributable requests go |
| `pricing.py`, `ledger.py` | official prices and the counterfactual ledger |
| `app.py` | the proxy |
| `memory.py` | personal memory in SQLite (preferences, project facts, accepted plans), each with origin and label |
| `delegate.py`, `sources.py` | `delegate`: fixed task templates over sources the gateway fetches itself |
| `mcp_server.py` | MCP server (stdio): `delegate`, `recall`, `quota` |
| `quota.py` | read-only Codex `rate_limits` from local session logs |
| `project_card.py` | generated block in `AGENTS.md` / `CLAUDE.md` from memory |

## Tool output that names no file

A tool message is labeled by the file path in its call (`read_file(path)`), through the learned rules. Output that is
not one file's content (a test run, a shell command) used to get the project default, so a failing test that printed
customer names went to Contributor: names are not detectable, and nothing in the call said where they came from. Two
deterministic mechanisms now label such output; the strictest label wins (`Config(output_paths=False,
fingerprints=False)` turns them off, which the bench uses as its "before").

**1. Paths printed in the output and named by the command.** `outpaths.py` finds Python `File "…"` lines,
`path:line[:col]` (also grep's `path:line:text`), pytest `path::test`, compiler/linter output, absolute POSIX and
Windows paths, `./x`, `dir/file.ext`, git diff headers, and in the call's `command`/`cmd`/`script`/`args`/`argv`/`target`
arguments also bare file names. Each is judged like a tool-call path: the strictest matching rule, and **no rule means
CONFIDENTIAL** until reviewed (and the path joins the review queue). A relative path is placed with the call's
`cwd`/`workdir`, else `x-cm-root`, else the root the system prompt states, else a path already seen in the session or
the review queue; if none works it is treated as unreviewed. Library frames (`site-packages`, `node_modules`,
`/usr/lib`, …) are ignored, and a bare `main.py` counts only with a line number or in a command. A file *read* is not
affected: its label is the file's, whatever paths its text mentions.

**2. Content fingerprints.** Whenever the gateway sees the content of a file (or of a file named in a command) whose
label is CONFIDENTIAL or stricter (unreviewed counts), it remembers distinctive *terms* of that text, per source file:

| Term | Example | Weight |
|---|---|---|
| unusual word: 8+ letters, not in `common_words.txt` | a company name | 2 |
| identifier of 6+ characters with 3+ digits | a tax number | 2 |
| decimal with 4+ places | a negotiated rate | 2 |
| two consecutive capitalized words, one of them not common | a person's name | 2 |
| capitalized unusual 5-7 letter word, 6+ digit string, 3-place decimal | a first name | 1 |

Source code (by extension) contributes only its string literals and numeric constants, since identifiers are shared
between files and say nothing about sensitivity. Later, a tool message that is not a named file's content (and a
user message after the first) whose terms score 2 or more takes the source's label. Hits are resolved against the
source's **current** label at lookup time: a file the user later reviews as public or OWN_IP stops protecting
anything, and a file reviewed after the fact is never remembered. Words that appear in the system prompt or the first
user message are exempt (the project's own name, or a name the user typed). The index lives in process memory only,
holds keyed 64-bit hashes (the key is random per process), is not persisted, logged, put in the ledger or sent.
It is gateway-wide: names read in one session protect the output of another.

`Decision.reason` (ledger) names the mechanism, e.g. `1 message(s) not contributable [fingerprint, output-path]`.

Limits: the first sight of a name is not protected (a test that prints names nobody read through the gateway before,
for instance data that lives only in a fixture or generator the agent never opened); paraphrases and translations are
not matched; text that is sensitive only in context is not matched (that needs a semantic judge); a name that is
also an ordinary word is a false-positive risk, a short or common one a miss; output paths with spaces are not
found; the fingerprint score is a heuristic whose cost is measured in `bench/` (`README.md` there).

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

Environment: `META_API_KEY`, `META_API_BASE`, `CONTRIBUTOR_MODEL`, `STANDARD_MODEL`, `LEDGER_PATH`, `CM_BILLING`,
`LOCAL_API_BASE`, `LOCAL_MODEL` (as the gateway; on credits a `delegate` call with an `instruction` is held or runs locally),
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
