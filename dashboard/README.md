# dashboard

The Compute Mint dashboard (Next.js): billing mode, savings against an all-Standard counterfactual, where each request
went and why, the exact masked context that left the machine, the review queue, and the bench evidence.

![overview](docs/screenshots/01-overview-1920x1080.png)

It reads the gateway through a same-origin proxy (`app/api/gw/[...path]`) that forwards only the read-only views and
the review decision, and it reads `bench/sample_results/reference-run/results.json` and `learning_curve.csv` on the server. It calls no model.

## Run the demo (no API key, no network)

Three terminals from the repository root. The gateway venv is built as in `gateway/README.md`.

```bash
# 1. demo data: synthetic sessions through the real gateway on a mock upstream -> dashboard/demo-data/*.db
cd gateway && .venv/Scripts/python -m demo.seed
```

```bash
# 2. the gateway on that data (Windows PowerShell: set the variables with $env:NAME="..." first)
cd gateway && LEDGER_PATH=../dashboard/demo-data/ledger.db POLICY_PATH=../dashboard/demo-data/policy.db CM_BILLING=credits .venv/Scripts/python -m uvicorn compute_mint.app:app --port 8787
```

```bash
# 3. the dashboard on http://localhost:3000 (add ?lang=zh for Traditional Chinese)
cd dashboard && npm install && npm run build && npm run start
```

`npm run dev` works too. `GATEWAY_URL` (default `http://127.0.0.1:8787`) points the dashboard at another gateway;
`BENCH_RESULTS` at another bench run. Stop the gateway before re-seeding: the seed replaces the two `.db` files.

### What the seed contains

`gateway/demo/seed.py` drives scripted agent sessions over the invented repositories in `bench/materials/` (slugkit,
public; billflow, a fictional company's invoicing service) through `create_app` with an `httpx.MockTransport` as the
model. No real session content is used. Timestamps are spread over the last three hours. Three phases make every lane
appear:

| Phase | Billing | Non-contributable requests go to |
|---|---|---|
| 1. comparison | `paid` | Standard (the only Standard rows; marked `paid` in the table) |
| 2. | `credits`, no local model | held (403) |
| 3. | `credits`, local model | local |

It includes a pasted API key, a customer e-mail and a phone number (masked as `⟨API_KEY_1⟩`, `⟨EMAIL_1⟩`,
`⟨TW_PHONE_1⟩`), a `.env` read (held), a session resumed from another vendor's model (held by origin), test output that
names an unreviewed file (held, `[output-path]`), and customer names in test output (local). Between phases 2 and 3 two
review decisions are made (slugkit's code and tests are public), so the slug task held in phase 2 is contributed in
phase 3. Seven paths stay in the review queue. The seed checks that no planted canary value reached a Contributor
request and that on credits only Contributor requests reached the mock Meta host.

### The review demo

1. In **Review queue**, press **Public** on `/work/slugkit/docs/**`. The gateway turns the decision into a rule.
2. Resend the sessions behind the queued paths:

   ```bash
   cd gateway && .venv/Scripts/python -m demo.seed --replay
   ```

   The docs session now goes to Contributor; `billflow/shared/**`, still unreviewed, is held. The page picks up the
   new rows within four seconds.

## Sections

| Section | Source |
|---|---|
| Billing mode | `GET /v1/status`: `credits` or `paid`, and where non-contributable requests go |
| Saved, e, cache hit, credits used, stayed local | `GET /v1/ledger/summary` (`?session=` with the session filter) |
| Effective compute × | Recomputed on the page from the request rows, see "The compute × figure" below |
| Same $1 | `summaries` of the bench reference run (arms 1 and 5) |
| Flywheel curve | `learning_curve.csv` of the bench reference run (arms 1, 3, 5, 6) |
| Where requests went, timeline, requests table | `GET /v1/ledger/requests` (newest 500 rows) |
| What left this machine | `GET /v1/ledger/requests/{id}`: `sent_payload` of a Contributor request, placeholders highlighted. Defaults to the newest one with masked values; click a Contributor row or dot to show another |
| Review queue | `GET /v1/review`, `POST /v1/review/{id}`. Paths that share a suggested pattern are shown together, because one decision settles all of them |
| Bench evidence | `summaries` of the bench reference run: acceptance, e, compute multiplier, canary violations |

Numbers are the gateway's own definitions: a local request costs nothing and counts its Standard price as the
counterfactual; a held request has neither. Amounts in the demo are cents because the sessions are short.
"Saved" keeps that definition; the compute × figure does not, see below.

### The compute × figure

The gateway's `effective_compute_multiplier` is counterfactual ÷ spent over all requests. A local request spends $0
but keeps its Standard price in the counterfactual, so every local request raises the multiplier without any model
discount being involved: the seed data shows **9.11×** this way. The page therefore recomputes it over the requests
that were billed, Contributor and Standard (6.14× on the seed data), and the card says how many local requests it
left out and what they would have cost on Standard. Held requests have neither cost nor counterfactual. The
gateway is unchanged and `/v1/ledger/summary` still returns 9.11×.

The recomputation needs every row, and the page loads the newest 500. If a view has more requests than that, or no
local request, the card shows the gateway's figure (the first case with a warning that it overstates). Even the
recomputed number is inflated by the seed's tiny, very discounted Contributor requests; the figure to quote is the
bench's, below.

### Same $1 and the flywheel (bench evidence, mock upstream)

Both panels sit under the KPIs and are labeled with the bench's upstream (`mock`): they show how routing, masking and
rule learning change cost on 37 synthetic tasks, not a measurement on the real API.

- **Same $1**: all Standard 1.00× against Mint + Broker + rule learning 1.66× (`compute_multiplier` of arms 1 and
  5, the same numbers as the bench table), 37/37 accepted in both. "Tasks per $1" is passed tasks ÷ paid dollars of
  the bench run ($0.1916 and $0.1156), so it is the same ratio again. The bars grow and the numbers count up once on
  load (not with `prefers-reduced-motion`).
- **Flywheel**: cumulative e (share of tokens served by Contributor) against task order for all Standard, Mint,
  Mint + rule learning and the oracle ceiling (every path rule known from the start). End points are the summary's
  0.0%, 9.8%, 48.5% and 52.9%. Bars under the plot are the review decisions made during each task (growth of
  `rules_learned`; 35 in all), and the shaded stretch ends at the task by which 91% of them were made. The curve is
  not a smooth climb: the first tasks swing because few have run, and the task mix is not uniform, so the caption
  says to read the end points. What it shows is that Mint without rules stays near 10% while the arm that learns
  from review decisions reaches the oracle's neighbourhood. Hover for the values of one task.

### Recording mode: `?present=1`

`http://localhost:3000/?present=1` (with `&lang=zh` for Chinese) is the layout for the 3-minute video at 1920×1080:
everything is scaled 1.2× on screens at least 1400 px wide, the session picker, language switch, "updated" time,
request table and footer are not rendered, and the rest is as in the normal page, in the same order (billing mode,
KPIs, same $1 and flywheel, lanes, payload and review queue, bench table). Without the parameter nothing changes.

## Design

Blue and white, system fonts (Inter if installed). The brand is Compute Mint with its own coin-and-leaf mark; no
provider logo or trademark is used. Lane colors were checked with a color-vision-deficiency palette validator
(contributor blue, local green, held orange pass all pairs; Standard is a deliberate neutral gray), and every lane is
also labeled in text. Built for a 1920×1080 recording; works down to phone width.

Screenshots: `docs/screenshots/` (01 overview at 1920×1080, 02 full page, 03 full page in Traditional Chinese,
04 phone width in Chinese, 05 after a review decision and `--replay` (made before the compute × change), 06 and 07
same $1 and flywheel in English and Chinese, 08 and 09 recording mode).

```bash
npm run lint
npm run build
```
