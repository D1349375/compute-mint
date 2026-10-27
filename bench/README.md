# bench

Acceptance tasks and measurement tools for Compute Mint. It answers, with numbers that can be re-run:

- what share of tokens can go to Muse Spark Contributor compliantly (**e**),
- whether the agent's work is still accepted (**acceptance rate**),
- what was paid, and what the same work costs on Standard (**counterfactual**, **compute multiplier**),
- prompt-cache hits and the Context Broker's compression,
- and whether anything that must not reach Contributor did (**canary violations**, target 0).

This round everything runs against a **mock upstream**. `--upstream meta` is reserved; it refuses to run.
Nothing in bench opens a network connection (a test blocks every non-loopback connection and runs the
bench under it).

```bash
cd <repo>
gateway/.venv/Scripts/python -m bench.run --arms all --upstream mock            # five arms, ~4 minutes
gateway/.venv/Scripts/python -m bench.run --arms all,oracle,mint_strict --out bench/sample_results --run-id reference-run
gateway/.venv/Scripts/python -m bench.run --arms standard,mint --tasks T01,T14   # a few tasks
cd bench && ../gateway/.venv/Scripts/python -m pytest -q                         # bench tests (~4 minutes)
```

(`gateway/.venv` is built as described in `gateway/README.md`; use `.venv/bin/python` on Linux/macOS.)
Output goes to `bench/results/<timestamp>/` (git-ignored): `results.json` (everything, no timestamps, byte-identical
for the same configuration), `summary.md`, `tasks.csv`, `learning_curve.csv`, `violations.csv`, `meta.json`.
A reference run is committed in `bench/sample_results/reference-run/`.

## What is simulated, and how

```
task script ──► scripted solver (the "model") ◄── mock upstream: token estimate + prefix-cache simulation
      │                  ▲                                  ▲
      ▼                  │ OpenAI-compatible                │ usage { prompt, cached, completion }
 agent loop ────────► gateway (create_app + TestClient) ────┘      recorded copy of every outgoing body
 list_files / read_file /       lanes, masking, origin,                   │
 write_file / run_tests         path rules, Context Broker, ledger        ▼
                                                                 canary scan, ledger cross-check
```

- **Agent loop** (`agent.py`, `tools.py`): a minimal tool-calling loop over four tools on a throw-away copy of a
  synthetic repository. `run_tests` runs real pytest in a subprocess with a minimal environment. Tool paths are
  absolute (`/work/<repo>/...`), as in real coding agents, so a path rule learned for one repository can never
  match another repository's file.
- **Scripted solver** (`solver.py`): each task carries the script of tool calls a competent agent makes and the files
  it writes (`solutions/<task id>/`). It reads only what the gateway sent it, so Contributor requests show it
  masked text; quoted values may be placeholders that the gateway restores in the reply. If a value it needs was
  compacted away by the Context Broker it re-reads the file once (that costs a request). It never makes a mistake.
- **Tokens** (`tokens.py`): no tokenizer is available offline. ASCII text counts 3.5 characters per token, every
  other character one token, +4 per message. The same estimator is used in every arm.
- **Prompt cache** (`cachesim.py`): longest-common-prefix matching over the serialized prompt (tool schema, then one
  JSON string per message), a trie per model shared across sessions, cached tokens rounded down to 64-token blocks,
  at least one token always uncached. No TTL, no minimum length. Cost is computed by the gateway's ledger with the
  official Standard and Contributor prices and the cache-aware formula; in a real run the ledger gets the API's usage.
- **Canary check** (`canary.py`): every request body that leaves the gateway is copied by a recording transport
  (independent of the ledger; a test checks the two agree) and scanned for the planted fake sensitive values.

## The synthetic material

Everything is invented (no real session content, no real personal data). `materials/<repo>/` holds
`files/` (the repository), `labels.json` (the true label of every file: PUBLIC / OWN_IP / CONFIDENTIAL / FLOOR) and
`canaries.json` (every fake sensitive value with the label it must never be sent under). The simulated reviewer
reads the labels; the canary check reads the canaries. `.env` and `.gitignore` are stored as `_dot_env` and
`_dot_gitignore` (the project `.gitignore` would skip them). Fake values avoid formats that secret scanners know,
so the repository can be made public; tests check that.

| Repo | What it is | Declared to the gateway as | Sensitive material |
|---|---|---|---|
| `slugkit` | small public Python library with docs, 9 modules, tests, 7 planted bugs | project `public`, dial `public` | a local `.env` (publish token, API key; FLOOR), an unannounced codename in an internal release draft (OWN_IP); the maintainer's published address is public but looks like an e-mail, so it gets masked |
| `billflow` | internal invoicing service of a fictional company | project `own_ip`, dial `own_ip` | customer names and tax ids (CONFIDENTIAL), contact people, e-mails and phones (FLOOR), `.env`, `auth.json`, a bill-run log with a bearer token, negotiated rates, a contract summary, a runbook, a sample invoice export |

Truth labels are per file; a directory the owner treats as one unit has one label. Tasks with `scope: public` are
sessions the owner scopes to a generic, publishable sub-problem inside the private checkout (project and dial
`public`). Prompts follow the project label: they may contain detectable personal data (it is masked) but never
undetectable business secrets, which would be the user's labeling mistake rather than the gateway's.

## The task set (37 tasks)

Order = the order of the simulated timeline (public and private interleaved); the first 19 are the *early* phase,
the last 18 the *late* phase. Each task has a deterministic acceptance: pytest on the visible tests and/or held-out
tests (`accept/<id>/`, copied in after the agent finished), a regex check on the final answer, or on a file.
`tests/test_tasks.py` checks for **every** task that the acceptance fails on the untouched repo and passes with the
correct solution.

| # | Task | Repo | Kind | Scope | Notes |
|---|---|---|---|---|---|
| 1 | `T01-slug-max-length` | slugkit | bug | repo | resumed_from_claude |
| 2 | `T02-money-split` | billflow | bug | repo |  |
| 3 | `T03-versions-numeric` | slugkit | bug | repo |  |
| 4 | `T04-log-failed-invoice` | billflow | explain | repo | reads_personal_data, info_in_long_output |
| 5 | `T05-textutil-truncate` | slugkit | feature | repo | big_output |
| 6 | `T06-invoice-tax-rounding` | billflow | bug | repo | resumed_from_claude |
| 7 | `T07-durations-hours` | slugkit | bug | repo |  |
| 8 | `T08-duedates-eom` | billflow | bug | repo |  |
| 9 | `T09-durations-fraction-error` | slugkit | explain | repo |  |
| 10 | `T10-discount-tier-boundary` | billflow | bug | repo | reads_confidential |
| 11 | `T11-template-missing-key` | slugkit | bug | repo |  |
| 12 | `T12-serialize-invoice` | billflow | feature | repo |  |
| 13 | `T13-docs-ranges-retry` | slugkit | docs | repo |  |
| 14 | `T14-notify-singular-day` | billflow | bug | repo | leak_vector:test_output |
| 15 | `T15-shared-chunked` | billflow | bug | public | public_only |
| 16 | `T16-lru-get-recency` | slugkit | bug | repo |  |
| 17 | `T17-settings-quotes` | billflow | bug | repo | reads_credentials |
| 18 | `T18-publish-401` | slugkit | explain | repo | reads_credentials |
| 19 | `T19-decimal-conversion-syntax` | billflow | explain | public | public_only |
| 20 | `T20-exporter-quoting` | billflow | bug | repo | leak_vector:test_output |
| 21 | `T21-ranges-unsorted` | slugkit | bug | repo |  |
| 22 | `T22-latefees` | billflow | feature | repo | resumed_from_claude |
| 23 | `T23-redact-plain-phone` | billflow | bug | repo | masks |
| 24 | `T24-csv-delimiter` | slugkit | feature | repo |  |
| 25 | `T25-runbook-smtp-rotation` | billflow | docs | repo | reads_confidential |
| 26 | `T26-clients-find-case` | billflow | bug | repo | leak_vector:test_output |
| 27 | `T27-retry-attempts` | slugkit | bug | repo | resumed_from_claude |
| 28 | `T28-shared-wrapping` | billflow | feature | public | public_only |
| 29 | `T29-changelog-0-3-0` | slugkit | docs | repo | needs_own_ip |
| 30 | `T30-legacy-two-digit-year` | billflow | bug | repo | reads_confidential |
| 31 | `T31-humanize-si` | slugkit | feature | repo |  |
| 32 | `T32-contract-payment-terms` | billflow | explain | repo | reads_confidential, info_in_long_output |
| 33 | `T33-pytest-fixture-not-found` | billflow | explain | public | public_only |
| 34 | `T34-client-terms-report` | billflow | feature | repo | reads_personal_data |
| 35 | `T35-readme-quickstart` | slugkit | docs | repo |  |
| 36 | `T36-currency-keyerror-email` | billflow | explain | repo | masks, rehydration |
| 37 | `T37-sync-invalid-grant` | billflow | explain | repo | reads_credentials |

Tags: `resumed_from_claude` = the history starts with turns written by another vendor's model (never contributable);
`reads_*` = the agent opens a credential, confidential or personal-data file; `leak_vector:test_output` = the test
failure prints customer names (see findings); `masks`/`rehydration` = detectable personal data in the prompt or tool
output is masked and restored; `public_only` = a private-repo session that needs only public information;
`info_in_long_output` = the answer depends on a value in the middle of a long output that the Context Broker may
compact (the solver then re-reads).

## The arms

| Arm | What runs |
|---|---|
| `standard` | everything on Standard through the gateway with the project declared `confidential` (no Mint, no Broker): the cost baseline |
| `naive` | **simulated only**: at a switch point the full raw history goes to Contributor. It is computed from the histories the Standard arm recorded and has no client, transport or URL (a test checks the module imports no HTTP stack). Reports what would have left and how much of it is a violation. Switch points: `start`, `mid` (default, after half of the requests), `late` |
| `mint` | lanes, masking and origin; the gateway as it is, no path rules, no Broker |
| `mint_broker` | `mint` + Context Broker |
| `mint_learn` | `mint_broker` + the review queue answered by a simulated reviewer from the truth labels (default: up to 2 decisions after each task; it generalizes a folder only if every file in it has the same answer) |
| `oracle` (extra) | `mint_broker` with every path rule preloaded from the truth: the ceiling for learning |
| `mint_strict` (extra) | `mint_learn` plus a **what-if shim** (`shims.py`, no gateway change): tool output that names no file is treated as unreviewed |

`--arms all` is the first five. The Standard arm always runs (it is the reference). Each arm gets its own gateway
app, ledger, policy and mock upstream, and sees the same tasks in the same order.

## Metrics

| Metric | Definition |
|---|---|
| e | tokens (prompt + completion) in Contributor requests / all tokens. For `naive`: only Contributor requests that carried nothing forbidden |
| acceptance | tasks whose deterministic acceptance passed / tasks |
| paid, counterfactual | the ledger's cost; the counterfactual is the Standard arm's cost for the same tasks (so it includes the Broker's effect; the ledger's own per-request counterfactual is in `results.json` as `ledger_multiplier`) |
| compute multiplier | counterfactual / paid |
| cache hit | cached prompt tokens / prompt tokens |
| broker ratio | characters sent / characters before the Broker (1.0 = untouched) |
| masked spans | values the gateway replaced by placeholders |
| violations | (Contributor request, canary) pairs, plus origin violations (text written by another vendor's model in a Contributor request); also reported as incidents (task, canary), violating requests and tasks |

`learning_curve.csv` has, per task in timeline order: the task's e, cumulative e, e over the last 5 tasks, and the
number of learned rules, for every arm.

## Findings of the reference run

See `sample_results/reference-run/summary.md`. Read it with these in mind:

1. **The canary check found a real gap.** The gateway labels a tool output by the file path in the tool call's
   arguments; the output of `run_tests` (or a shell command) names no file, so it gets the project default label. When
   a failing test prints customer names, the names go to Contributor (names are not detectable). All violations in
   the Mint arms come from the three `leak_vector:test_output` tasks. Learning makes it worse (the lane stays
   Contributor longer, so the same names are sent in more requests). `mint_strict` shows the price of closing it
   crudely: no violations, but e falls from about half to about a fifth. A finer fix is for the gateway's owner to design.
2. A careless review decision is not caught by the gateway (`tests/test_arms_e2e.py` creates one on purpose and
   checks that the canary scan sees it).

## Moving to the real API

The loop, arms, canary scan and reports do not depend on the mock. When the models are approved:

1. implement `MetaUpstream.transport()` (`upstream.py`) as `httpx.AsyncHTTPTransport()` with `META_API_KEY`, wrapped in
   `RecordingTransport` as the mock is; drop the guard in `run.py`;
2. replace the scripted solver by a real model behind the same endpoint (the task `steps` are then unused; prompts,
   repositories and acceptance stay);
3. `usage` and cached tokens then come from the response, so `tokens.py` and `cachesim.py` are not used;
4. the `naive` arm stays analysis-only: it reads the Standard arm's recorded histories and has no way to send them.

Real runs cost money and are not deterministic: run each arm more than once before comparing.

## Biases and limits (read before quoting a number)

- **The solver is ideal.** It never takes a wrong turn, so acceptance is near 100% by construction in every arm; only
  the Context Broker's information loss (re-reads) can show up. A real model on masked or compacted context will fail
  more often, and the gap between arms is what that run must measure.
- **Token counts are estimates** (3.5 characters/token, no tokenizer; plausible error ±25%). Ratios between arms are
  more robust than absolute dollars.
- **Short sessions and small repositories.** Tasks take 2 to 6 requests; real sessions run for hundreds of turns with a
  cached prefix of 98% (the project's own analysis). Cache hit rates here (72 to 78%) and the Context Broker's
  compression (few tool outputs exceed its 4000-character threshold) understate both. The system prompt is about
  1k tokens; real agents carry 10k or more.
- **The cache model** has no TTL and no minimum length and shares prefixes across sessions.
- **Learning depends on revisits.** The corpus has about 80 files; most directories are met early, so rules saturate
  quickly (20 decisions in 37 tasks) and the late phase is not "more learned" so much as a different mix. Compare an
  arm with the `oracle` ceiling, not early with late.
- **The reviewer is perfect by default.** `--reviewer-error-rate` makes it careless.
- **Canaries are what was planted.** Zero violations means none of these values got through, not that nothing could.
  Prompts contain no undetectable secrets by design; a user who pastes a customer name into a prompt is not defended
  by the gateway and is not measured here.
- **Project and dial per repo are assumptions** (public repo: `public`/`public`; private repo: `own_ip`/`own_ip`;
  scoped sessions `public`). A private repo declared `confidential` would send nothing to Contributor.
- **Origin is exercised by four resumed-session tasks** only; the gateway's own tests cover it more deeply.
- **One deterministic run, no variance estimate.** Task order and the reviewer's FIFO queue are fixed.
- The `standard` arm goes through the gateway (project `confidential`) rather than straight to the upstream; with
  the Broker off the request bodies are the agent's own, so the cost is that of a direct Standard run.

## Layout

| Path | |
|---|---|
| `run.py` | CLI and orchestration |
| `arms.py`, `armtypes.py` | the arms; the runner that drives a gateway app; shared types (no network imports) |
| `naive.py` | analysis-only arm |
| `agent.py`, `tools.py`, `solver.py`, `upstream.py` | agent loop, tools, scripted model, mock and reserved upstreams |
| `tokens.py`, `cachesim.py` | token estimate and prefix-cache simulation |
| `canary.py`, `acceptance.py`, `reviewer.py`, `shims.py` | canary scan, deterministic acceptance, simulated reviewer, what-if shim |
| `metrics.py`, `report.py` | aggregation and output files |
| `taskmodel.py`, `taskset.py`, `tasks_public.py`, `tasks_private.py`, `repos.py` | tasks and materials |
| `materials/` | the two repositories, their truth labels and canaries, `gen_bulk.py` (regenerates the bulky files) |
| `solutions/`, `accept/` | correct solutions per task; held-out acceptance tests |
| `tests/` | bench tests |
