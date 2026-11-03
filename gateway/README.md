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

Both `POST /v1/chat/completions` and `POST /v1/responses` take these headers, stream or not (see [Streaming](#streaming) and [Responses API](#responses-api-and-codex)).

`GET /v1/ledger/summary` returns spend, counterfactual spend, savings, the contributable token share, the cache hit rate, the Context Broker's context ratio, held and local request counts, and the spend paid with credits.

Read-only views for the dashboard: `GET /v1/ledger/requests` (newest first; `session`, `lane`, `limit` 1–500,
`offset`; `payload=true` adds what left the machine in a Contributor request: `sent_payload`, the masked messages, and
`sent_fields`, the rest of the body such as tool definitions, also masked; old rows have `sent_fields` null), `GET /v1/ledger/requests/{id}`,
`GET /v1/ledger/sessions`, and `GET /v1/status` (billing mode, local model if configured, model names).

`python -m demo.seed` writes demo data for the dashboard without an API key: scripted sessions over the invented
repositories in `bench/materials/` sent through the gateway on a mock upstream (see `dashboard/README.md`).

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
| `detect.py` | deterministic credential / personal-data detectors; word boundaries are ASCII, so a value glued to Chinese text is found whole, and full-width forms count |
| `vault.py` | session-consistent placeholders and rehydration; restored tool-call arguments stay valid JSON |
| `cjk.py` | name-shaped fingerprint terms in Chinese, Japanese and Korean text |
| `context.py` | taint tracking; provenance of gateway-generated replies |
| `router.py` | lane decision and clean-context assembly |
| `broker.py` | cache-aware Context Broker: compacts aged tool outputs once, memoized, so the cached prefix keeps matching |
| `policy.py` | learned path rules and the review queue; credential files are always FLOOR; labels tool output that names no file (below) |
| `outpaths.py` | file paths in free text: tracebacks, `path:line`, pytest ids, compiler output, shell commands |
| `fingerprint.py` | content fingerprints of sensitive text read earlier (in-memory, keyed hashes) |
| `billing.py` | paid vs credits: where non-contributable requests go |
| `pricing.py`, `ledger.py` | official prices and the counterfactual ledger |
| `app.py` | the proxy: one path (`admit`, `upstream_body`, `settle`) behind both endpoints |
| `streaming.py` | SSE relay: restores placeholders cut between deltas, assembles the reply for provenance, settles the ledger however the stream ends |
| `responses.py` | Responses API requests to chat messages, chat chunks to Responses events |
| `memory.py` | personal memory in SQLite (preferences, project facts, accepted plans), each with origin and label |
| `delegate.py`, `sources.py` | `delegate`: fixed task templates over sources the gateway fetches itself |
| `mcp_server.py` | MCP server (stdio): `delegate`, `recall`, `quota` |
| `quota.py` | read-only Codex `rate_limits` from local session logs |
| `project_card.py` | generated block in `AGENTS.md` / `CLAUDE.md` from memory |

## Streaming

`stream: true` relays the upstream's server-sent events. Everything the non-streaming path guarantees still holds:

| | |
|---|---|
| Placeholders | A placeholder cut between two deltas is held back until it is complete or cannot become one, per choice and per tool call, and flushed when the stream ends. Only placeholders of this session's vault are held, so other text is never delayed. Standard and local lanes do not buffer. |
| Provenance, origin | Recorded when the stream finishes, from the assembled message the client saw (restored values included), with the same fingerprint as a non-streaming reply. `""`, `null` and a missing `content` hash alike, because clients spell an empty reply differently. A stream that did not finish records nothing, so a partial reply comes back as foreign, which fails closed. |
| Before the stream | Lane decision, the `held` 403, upstream 4xx/5xx and an unreachable upstream (502) are ordinary HTTP answers. |
| After it started | An upstream failure becomes `data: {"error": {"type": "upstream_stream_error", "code", "message"}}` then `data: [DONE]` (on `/v1/responses`, `response.failed`). |
| Headers | `x-cm-lane`, `x-cm-billing`, `x-cm-masked-spans`, `x-cm-broker-chars` as usual. Cost is not known yet when headers go out, so it comes as an SSE comment just before the end, `: x-cm-cost=0.000104 x-cm-counterfactual=0.001335`, which event-stream parsers ignore; the ledger has it too (`GET /v1/ledger/requests`). |
| Usage | The gateway always asks upstream for `stream_options.include_usage`. The usage chunk reaches the client only if the client asked for it, so nobody trips over a chunk with empty `choices`. |
| Ledger | One row when the stream ends, however it ends: client disconnect, upstream failure or upstream 4xx/5xx leave a row with the sent payload and a note in `reason` (`stream interrupted: …`), and the upstream connection is closed. |

Limits: a stream cut before the usage chunk records the usage seen so far, usually zero (Meta's docs say an interrupted stream may omit it), so its cost is understated and `reason` says so. A failed non-streaming request still leaves no ledger row, as before. A model that writes a placeholder in JSON escapes (`⟨…`) inside tool arguments is not restored, streaming or not.

## Responses API and Codex

`POST /v1/responses` translates the request into chat messages and takes the same path: labels, routing, billing, Broker, ledger. The upstream is always `/chat/completions`, also on Meta, which has its own `/v1/responses`: that one stores by default (`store: true`) and chains server-side history, while chat completions is stateless, is what local models speak, and keeps a single mask-and-restore path.

| Input | Becomes |
|---|---|
| `instructions` | a leading `system` message |
| `input` as a string, or `message` items | messages; `developer` becomes `system` (the same level on Meta, and local servers may not know it) |
| `function_call`, `custom_tool_call`, `local_shell_call` | `tool_calls` on one assistant message, joined to the text before them |
| `function_call_output` and friends | a `tool` message with the matching `tool_call_id`; output of any shape becomes text, so all of it is labeled and masked |
| `tools` | flat and nested `function` as functions; `custom` (e.g. `apply_patch`) and `local_shell` as functions, translated back in the output; hosted tools (`web_search`, …) are not offered |
| `max_output_tokens`, `text.format`, `reasoning.effort`, `tool_choice`, `temperature`, `top_p`, `parallel_tool_calls` | their chat equivalents. Nothing else goes upstream (`metadata`, `user`, `prompt_cache_key`, `include`, …) |

What is refused or dropped, and why:

| Item | Handling |
|---|---|
| `previous_response_id`, `conversation`, `prompt`, `background`, `item_reference` | **400, nothing sent.** They point at state stored elsewhere. The gateway keeps no store, and server-side context must never decide what a Contributor request holds (ToS §6.1). Send the whole input. `/v1/chat/completions` refuses the first three as well. |
| `store` | Always `false` upstream, on both endpoints when present. |
| `function_call_output` whose call is not in the input | **400.** The call's arguments are what `policy.py` labels the output by; without them it cannot be judged. |
| `reasoning` items, and any other model-generated item the gateway does not know | **Not sent on any lane**: encrypted blobs and text of unknown origin cannot be masked or judged. The gateway never emits reasoning itself, so one in the input means another model wrote it. Its presence also keeps the request off Contributor (on credits: local or `held`), and the reply is recorded as CONFIDENTIAL. |
| Images | Passed to Standard or local only: they cannot be labeled, so the same rule applies. `input_file` is a 400. In tool output an image is replaced by a marker. |

Provenance is recorded from the items the client will send back, translated exactly as an incoming request is, for every contiguous run of them: a client may replay parallel calls together or each followed by its output. `x-cm-client` works as on chat: a `message` or `function_call` the gateway did not generate counts as that origin. On Contributor the fields next to the messages (tool definitions and the like) are masked as well, on both endpoints.

Codex (`config.toml`; no key is needed here, the gateway holds the upstream key):

```toml
model = "muse-spark-1.3"          # ignored by routing: the gateway picks the model of the lane
model_provider = "compute-mint"

[model_providers.compute-mint]
name = "Compute Mint"
base_url = "http://localhost:8787/v1"
env_key = "CM_CLIENT_KEY"    # any non-empty value: Codex wants one, and the gateway uses its own META_API_KEY
wire_api = "responses"
http_headers = { "x-cm-client" = "openai", "x-cm-project" = "public", "x-cm-session" = "my-repo", "x-cm-root" = "/abs/path/of/my-repo" }
```

Checked with a real client: codex-cli 0.163.0-alpha.10.2, read-only sandbox, a throwaway `CODEX_HOME`, on a scripted mock upstream (no real model). Codex warns that it has no metadata for `muse-spark-1.3` and goes on. On a `held` answer the turn fails and shows the reason. Checked against the real Meta API with `python -m demo.real_smoke` (see `docs/BUILD_LOG.md`, 2026-11-04), not yet with Codex itself.

Without `x-cm-session` the session is a hash of the instructions, so Codex sessions with the same instructions share one vault and provenance. Without `x-cm-root` relative paths are placed from `<cwd>` in the first user message, else treated as unreviewed. Expect `held` on credits as soon as a file with no rule is read: answer the review queue (`GET /v1/review`) or configure a local model.

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

**Chinese, Japanese and Korean.** Paths and Latin terms glued to these scripts are found (`錯誤在config/a.py:3行`,
`統編TW90210017是`), and a few of their names are fingerprinted. These scripts have no spaces or capitals and the gateway
has no segmenter, so an unusual word cannot be told from an ordinary one, and **only what has the shape of a name is
remembered** (`cjk.py`):

| Term | Example | Where |
|---|---|---|
| anything ending in a legal form, with its tails | `台灣鳳梨股份有限公司`, `株式会社サクラ精機`, `한빛소프트 주식회사` | anywhere |
| the name without the legal form | `台灣鳳梨` | when the source run is just the company |
| a field ending in an organization word, unless generic | `永昌會計師事務所`, not `物流公司` | a field: bounded by non-CJK text, not prose |
| a field of the shape surname + given name | `王小明`, `歐陽靖`, `佐藤花子`, `김철수`, not `高雄市` | same |
| a name after a label or before a title | `聯絡人：陳大文`, `王小明先生` | anywhere |

All of these weigh 2, so one hit is enough, also from an unreviewed source. `python -m bench.fpaudit_cjk` measures the
cost, on invented customer data (6 sources and 2,000 generated rows):

| Public text | Lines | Held back |
|---|---|---|
| Windows messages, zh-TW | 182,766 | 0 |
| Chromium UI strings, zh-TW / zh-CN / ja / ko | 5,020 / 5,499 / 5,518 / 5,369 | 0 / 0 / 0 / 0 |
| `docs/PLAN.md` and hand-written public tool output | 53 | 0 |

The worst case is a sensitive table that holds ordinary words as fields, which would make them terms: 0.05% of the
Windows fields and 0.02% of the Chromium Chinese ones have the shape of a name, 0.08% Japanese, 0.19% Korean. The stoplists were tuned on
this same text, so read those as optimistic. It caught all 15 test mentions (spaced, glued, in JSON, four scripts).

Not protected, on purpose or for lack of a segmenter (a test keeps this list honest): two-character names (`王明`);
surnames that are not on the list and foreign names written in CJK; ordinary-looking fields, however confidential
(`重要客戶`), so a reviewed confidential file protects far less in Chinese than in English, where any unusual word
counts; a person named only in running prose with no label or title (`這件事由陳美玲負責`); other spellings and scripts
(`臺灣鳳梨` for `台灣鳳梨`, simplified for traditional); more than 100,000 CJK characters of one text. A company's own
directory glued to prose (`客戶data/a.csv`) is read as `data/a.csv`. Email addresses with a non-ASCII local part are
not detected.

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
