import type { RequestRow, Summary } from "./types";

/**
 * The gateway counts a local request as $0 spent but keeps its Standard price in the counterfactual, so its
 * `effective_compute_multiplier` grows with every local request without any model discount being involved.
 * The page recomputes the multiplier over the requests that were billed (Contributor and Standard).
 *
 * `kind`:
 * - "cloud": recomputed over the loaded rows, local requests left out (`localRequests`, `localCf` say how much);
 * - "gateway": no local request, so the gateway's figure is already exact;
 * - "truncated": there are local requests but not every row is loaded (the page loads the newest 500), so the
 *   gateway's inflated figure is all there is.
 */
export interface CloudMultiplier {
  kind: "cloud" | "gateway" | "truncated";
  value: number | null;
  /** Standard-priced cost and billed cost of the requests counted (kind "cloud" only). */
  cf: number;
  cost: number;
  localRequests: number;
  localCf: number;
}

export function cloudMultiplier(s: Summary, rows: RequestRow[]): CloudMultiplier {
  const base = { cf: s.counterfactual_usd, cost: s.spent_usd, localRequests: s.local_requests, localCf: 0 };
  if (s.local_requests === 0) return { kind: "gateway", value: s.effective_compute_multiplier, ...base };
  if (rows.length < s.requests) return { kind: "truncated", value: s.effective_compute_multiplier, ...base };
  let cost = 0;
  let cf = 0;
  let localCf = 0;
  for (const r of rows) {
    if (r.lane === "local") localCf += r.counterfactual;
    else {
      cost += r.cost;
      cf += r.counterfactual;
    }
  }
  return { kind: "cloud", value: cost > 0 ? cf / cost : null, cf, cost, localRequests: s.local_requests, localCf };
}
