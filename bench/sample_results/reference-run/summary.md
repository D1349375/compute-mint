# Compute Mint bench: summary

37 tasks (19 early, 18 late), 15 on the public repo and 22 on the private one. Upstream: **mock**. Reviewer budget: 2 decisions per task, error rate 0.0. Cache block: 64 tokens.

## Headline

| Arm | Acceptance | e | Paid | Counterfactual (all Standard) | Compute multiplier | Cache hit | Broker ratio | Masked spans | Canary violations |
|---|---|---|---|---|---|---|---|---|---|
| 1. All Standard (no Mint) | 37/37 (100.0%) | 0.0% | $0.1916 | $0.1916 | 1.00x | 77.7% | 1.00 | 0 | 0 (0 tasks) |
| 2. Naive mid-session switch (simulated only) | n/a (not executed) | 37.8% compliant, 72.3% unchecked | n/a | $0.1916 (hypothetical Contributor cost $0.0965) | n/a | n/a | n/a | 0 (not masked) | **207** (18 tasks) |
| 3. Compute Mint (lanes + masking + origin) | 37/37 (100.0%) | 9.8% | $0.1809 | $0.1916 | 1.06x | 76.7% | 1.00 | 2 | 0 (0 tasks) |
| 4. Compute Mint + Context Broker | 37/37 (100.0%) | 10.3% | $0.1832 | $0.1916 | 1.05x | 74.1% | 0.93 | 2 | 0 (0 tasks) |
| 5. Mint + Broker + rule learning | 37/37 (100.0%) | 48.5% | $0.1156 | $0.1916 | 1.66x | 73.1% | 0.93 | 23 | 0 (0 tasks) |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 37/37 (100.0%) | 52.9% | $0.1071 | $0.1916 | 1.79x | 73.2% | 0.93 | 23 | 0 (0 tasks) |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 37/37 (100.0%) | 23.3% | $0.1584 | $0.1916 | 1.21x | 73.1% | 0.93 | 7 | 0 (0 tasks) |
| 5a. Arm 5 without the leak fix (before, extra) | 37/37 (100.0%) | 52.2% | $0.1146 | $0.1916 | 1.67x | 72.4% | 0.93 | 47 | 32 (3 tasks) |
| 5b. Arm 5 with output paths only (ablation, extra) | 37/37 (100.0%) | 55.4% | $0.1047 | $0.1916 | 1.83x | 73.1% | 0.93 | 51 | 32 (3 tasks) |
| 5c. Arm 5 with content fingerprints only (ablation, extra) | 37/37 (100.0%) | 45.3% | $0.1254 | $0.1916 | 1.53x | 72.4% | 0.93 | 19 | 0 (0 tasks) |
| 5d. Fingerprints only, threshold 1 (sweep, extra) | 37/37 (100.0%) | 45.3% | $0.1254 | $0.1916 | 1.53x | 72.4% | 0.93 | 19 | 0 (0 tasks) |
| 5e. Fingerprints only, threshold 4 (sweep, extra) | 37/37 (100.0%) | 45.3% | $0.1254 | $0.1916 | 1.53x | 72.4% | 0.93 | 19 | 0 (0 tasks) |

e = share of tokens served by Contributor (for the naive arm: share in Contributor requests that carried nothing forbidden). Counterfactual = the all-Standard arm's cost for the same tasks. Compute multiplier = counterfactual / paid. Canary violations count (Contributor request, canary) pairs; the target is 0.

Learning effort: 5. Mint + Broker + rule learning: 35 review decisions, 35 rules; 7. Arm 5 + distrust tool output without a file (what-if, extra): 35 review decisions, 35 rules; 5a. Arm 5 without the leak fix (before, extra): 20 review decisions, 20 rules; 5b. Arm 5 with output paths only (ablation, extra): 35 review decisions, 35 rules; 5c. Arm 5 with content fingerprints only (ablation, extra): 20 review decisions, 20 rules; 5d. Fingerprints only, threshold 1 (sweep, extra): 20 review decisions, 20 rules; 5e. Fingerprints only, threshold 4 (sweep, extra): 20 review decisions, 20 rules.

## Learning: early vs late tasks

| Arm | e early | e late | Acceptance early | Acceptance late | Share of oracle e, early | late |
|---|---|---|---|---|---|---|
| 1. All Standard (no Mint) | 0.0% | 0.0% | 100.0% | 100.0% | | |
| 2. Naive mid-session switch (simulated only) | 45.9% | 26.9% | n/a | n/a | | |
| 3. Compute Mint (lanes + masking + origin) | 8.8% | 11.2% | 100.0% | 100.0% | 15.3% | 23.7% |
| 4. Compute Mint + Context Broker | 9.3% | 11.6% | 100.0% | 100.0% | 16.2% | 24.6% |
| 5. Mint + Broker + rule learning | 49.5% | 47.1% | 100.0% | 100.0% | 86.2% | 100.0% |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 57.4% | 47.1% | 100.0% | 100.0% | 100.0% | 100.0% |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 17.6% | 30.8% | 100.0% | 100.0% | 30.7% | 65.3% |
| 5a. Arm 5 without the leak fix (before, extra) | 55.6% | 47.7% | 100.0% | 100.0% | 96.9% | 101.3% |
| 5b. Arm 5 with output paths only (ablation, extra) | 53.8% | 57.5% | 100.0% | 100.0% | 93.7% | 122.1% |
| 5c. Arm 5 with content fingerprints only (ablation, extra) | 51.3% | 37.3% | 100.0% | 100.0% | 89.4% | 79.2% |
| 5d. Fingerprints only, threshold 1 (sweep, extra) | 51.3% | 37.3% | 100.0% | 100.0% | 89.4% | 79.2% |
| 5e. Fingerprints only, threshold 4 (sweep, extra) | 51.3% | 37.3% | 100.0% | 100.0% | 89.4% | 79.2% |

The task mix differs between the two phases, so compare an arm with the oracle ceiling (every path rule known from the start) rather than early with late. The per-task series is in `learning_curve.csv` (x axis: task order).

## e by repository

| Arm | public repo (slugkit) | private repo (billflow) |
|---|---|---|
| 1. All Standard (no Mint) | 0.0% | 0.0% |
| 2. Naive mid-session switch (simulated only) | 58.7% | 20.3% |
| 3. Compute Mint (lanes + masking + origin) | 8.5% | 10.9% |
| 4. Compute Mint + Context Broker | 9.1% | 11.2% |
| 5. Mint + Broker + rule learning | 72.4% | 29.5% |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 72.4% | 37.5% |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 31.4% | 16.9% |
| 5a. Arm 5 without the leak fix (before, extra) | 61.8% | 44.6% |
| 5b. Arm 5 with output paths only (ablation, extra) | 72.4% | 41.9% |
| 5c. Arm 5 with content fingerprints only (ablation, extra) | 61.8% | 32.1% |
| 5d. Fingerprints only, threshold 1 (sweep, extra) | 61.8% | 32.1% |
| 5e. Fingerprints only, threshold 4 (sweep, extra) | 61.8% | 32.1% |

## Before and after the leak fix

Before = the reference run made with the gateway that labeled a tool output only by the file path in the tool call (`sample_results/before-leak-fix/`). After = this run: output labeled also by the paths it prints and by fingerprints of sensitive text read earlier.

| Arm | Acceptance | e | Compute multiplier | Canary violations | Origin violations |
|---|---|---|---|---|---|
| 1. All Standard (no Mint) | 37/37 → 37/37 | 0.0% → 0.0% | 1.00x → 1.00x | 0 → **0** | 0 → 0 |
| 3. Compute Mint (lanes + masking + origin) | 37/37 → 37/37 | 19.1% → 9.8% | 1.10x → 1.06x | 8 → **0** | 0 → 0 |
| 4. Compute Mint + Context Broker | 37/37 → 37/37 | 20.0% → 10.3% | 1.12x → 1.05x | 8 → **0** | 0 → 0 |
| 5. Mint + Broker + rule learning | 37/37 → 37/37 | 52.2% → 48.5% | 1.67x → 1.66x | 32 → **0** | 0 → 0 |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 37/37 → 37/37 | 67.3% → 52.9% | 2.27x → 1.79x | 32 → **0** | 0 → 0 |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 37/37 → 37/37 | 20.9% → 23.3% | 1.15x → 1.21x | 0 → **0** | 0 → 0 |

## Why requests stayed on Standard

Requests served by Standard, by the mechanism the gateway named in its routing reason (a request can be held back by several messages; "other" is path rules, detected secrets and origin).

| Arm | Standard requests | output path only | fingerprint only | both | other |
|---|---|---|---|---|---|
| 3. Compute Mint (lanes + masking + origin) | 133 | 91 | 0 | 0 | 42 |
| 4. Compute Mint + Context Broker | 133 | 91 | 0 | 0 | 42 |
| 5. Mint + Broker + rule learning | 74 | 23 | 12 | 0 | 39 |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 67 | 15 | 12 | 0 | 40 |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 110 | 0 | 0 | 0 | 110 |
| 5a. Arm 5 without the leak fix (before, extra) | 65 | 0 | 0 | 0 | 65 |
| 5b. Arm 5 with output paths only (ablation, extra) | 62 | 23 | 0 | 0 | 39 |
| 5c. Arm 5 with content fingerprints only (ablation, extra) | 77 | 0 | 12 | 0 | 65 |
| 5d. Fingerprints only, threshold 1 (sweep, extra) | 77 | 0 | 12 | 0 | 65 |
| 5e. Fingerprints only, threshold 4 (sweep, extra) | 77 | 0 | 12 | 0 | 65 |

## Naive switch: when is the model flipped?

| Switch point | e (compliant) | e (unchecked) | Violations | Violating requests | Tasks affected | Origin violations |
|---|---|---|---|---|---|---|
| start | 60.2% | 100.0% | 222 | 57 | 18 | 21 |
| mid | 37.8% | 72.3% | 207 | 44 | 18 | 12 |
| late | 14.9% | 29.5% | 96 | 18 | 18 | 4 |

start = whole task on Contributor; mid = after half of the requests (used in the headline); late = only the last request.

## Where the canaries got through (executed arms)

| Arm | Violations (request x canary) | Incidents (task x canary) | Requests | Tasks | Source in the request |
|---|---|---|---|---|---|
| learn_nofix | 32 | 8 | 12 | 3 | tool: run_tests (32) |
| learn_paths | 32 | 8 | 12 | 3 | tool: run_tests (32) |

Details per violation (task, request, canary, source): `violations.csv`.
