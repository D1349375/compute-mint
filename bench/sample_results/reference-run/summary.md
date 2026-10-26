# Compute Mint bench: summary

37 tasks (19 early, 18 late), 15 on the public repo and 22 on the private one. Upstream: **mock**. Reviewer budget: 2 decisions per task, error rate 0.0. Cache block: 64 tokens.

## Headline

| Arm | Acceptance | e | Paid | Counterfactual (all Standard) | Compute multiplier | Cache hit | Broker ratio | Masked spans | Canary violations |
|---|---|---|---|---|---|---|---|---|---|
| 1. All Standard (no Mint) | 37/37 (100.0%) | 0.0% | $0.1916 | $0.1916 | 1.00x | 77.7% | 1.00 | 0 | 0 (0 tasks) |
| 2. Naive mid-session switch (simulated only) | n/a (not executed) | 37.8% compliant, 72.3% unchecked | n/a | $0.1916 (hypothetical Contributor cost $0.0965) | n/a | n/a | n/a | 0 (not masked) | **207** (18 tasks) |
| 3. Compute Mint (lanes + masking + origin) | 37/37 (100.0%) | 19.1% | $0.1740 | $0.1916 | 1.10x | 72.4% | 1.00 | 13 | 8 (3 tasks) |
| 4. Compute Mint + Context Broker | 37/37 (100.0%) | 20.0% | $0.1708 | $0.1916 | 1.12x | 71.4% | 0.93 | 13 | 8 (3 tasks) |
| 5. Mint + Broker + rule learning | 37/37 (100.0%) | 52.2% | $0.1146 | $0.1916 | 1.67x | 72.4% | 0.93 | 47 | 32 (3 tasks) |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 37/37 (100.0%) | 67.3% | $0.0843 | $0.1916 | 2.27x | 73.0% | 0.93 | 52 | 32 (3 tasks) |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 37/37 (100.0%) | 20.9% | $0.1670 | $0.1916 | 1.15x | 72.5% | 0.93 | 3 | 0 (0 tasks) |

e = share of tokens served by Contributor (for the naive arm: share in Contributor requests that carried nothing forbidden). Counterfactual = the all-Standard arm's cost for the same tasks. Compute multiplier = counterfactual / paid. Canary violations count (Contributor request, canary) pairs; the target is 0.

Learning effort: 5. Mint + Broker + rule learning: 20 review decisions, 20 rules; 7. Arm 5 + distrust tool output without a file (what-if, extra): 20 review decisions, 20 rules.

## Learning: early vs late tasks

| Arm | e early | e late | Acceptance early | Acceptance late | Share of oracle e, early | late |
|---|---|---|---|---|---|---|
| 1. All Standard (no Mint) | 0.0% | 0.0% | 100.0% | 100.0% | | |
| 2. Naive mid-session switch (simulated only) | 45.9% | 26.9% | n/a | n/a | | |
| 3. Compute Mint (lanes + masking + origin) | 20.7% | 17.0% | 100.0% | 100.0% | 28.1% | 28.9% |
| 4. Compute Mint + Context Broker | 21.9% | 17.7% | 100.0% | 100.0% | 29.7% | 30.0% |
| 5. Mint + Broker + rule learning | 55.6% | 47.7% | 100.0% | 100.0% | 75.5% | 81.0% |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 73.6% | 58.9% | 100.0% | 100.0% | 100.0% | 100.0% |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 20.7% | 21.1% | 100.0% | 100.0% | 28.1% | 35.9% |

The task mix differs between the two phases, so compare an arm with the oracle ceiling (every path rule known from the start) rather than early with late. The per-task series is in `learning_curve.csv` (x axis: task order).

## e by repository

| Arm | public repo (slugkit) | private repo (billflow) |
|---|---|---|
| 1. All Standard (no Mint) | 0.0% | 0.0% |
| 2. Naive mid-session switch (simulated only) | 58.7% | 20.3% |
| 3. Compute Mint (lanes + masking + origin) | 18.6% | 19.6% |
| 4. Compute Mint + Context Broker | 20.0% | 20.1% |
| 5. Mint + Broker + rule learning | 61.8% | 44.6% |
| 6. Mint + Broker + oracle rules (ceiling, extra) | 81.7% | 55.9% |
| 7. Arm 5 + distrust tool output without a file (what-if, extra) | 25.8% | 17.0% |

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
| mint | 8 | 8 | 3 | 3 | tool: run_tests (8) |
| mint_broker | 8 | 8 | 3 | 3 | tool: run_tests (8) |
| mint_learn | 32 | 8 | 12 | 3 | tool: run_tests (32) |
| oracle | 32 | 8 | 12 | 3 | tool: run_tests (32) |

Details per violation (task, request, canary, source): `violations.csv`.
