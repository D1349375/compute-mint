// Shapes returned by the gateway's read-only endpoints (gateway/compute_mint/app.py).

export type Lane = "contributor" | "standard" | "local" | "held";
export const LANES: Lane[] = ["contributor", "standard", "local", "held"];

export type Billing = "credits" | "paid";

export interface Status {
  billing: Billing;
  local_model: string | null;
  contributor_model: string;
  standard_model: string;
}

export interface Summary {
  requests: number;
  spent_usd: number;
  counterfactual_usd: number;
  saved_usd: number;
  contributable_token_share: number;
  effective_compute_multiplier: number | null;
  cache_hit_rate: number;
  broker_context_ratio: number;
  held_requests: number;
  local_requests: number;
  credits_usd: number;
}

export interface RequestRow {
  id: number;
  ts: number;
  session: string;
  lane: Lane;
  model: string;
  context_label: string;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  cost: number;
  counterfactual: number;
  masked_spans: number;
  reason: string;
  chars_in: number;
  chars_out: number;
  billing: Billing;
  has_payload: boolean;
  sent_payload?: string | null;
}

export interface RequestPage {
  total: number;
  limit: number;
  offset: number;
  requests: RequestRow[];
}

export interface SessionRow {
  session: string;
  requests: number;
  first_ts: number;
  last_ts: number;
  spent_usd: number;
  counterfactual_usd: number;
}

export interface ReviewItem {
  id: number;
  path: string;
  suggested_pattern: string;
  hits: number;
}

export interface ReviewQueue {
  pending: ReviewItem[];
  rules: { pattern: string; label: string }[];
}

// Extracted from bench/sample_results/reference-run/results.json (lib/bench.ts).
export interface BenchArm {
  arm: string;
  title: string;
  executed: boolean;
  passed: number | null;
  tasks: number;
  pass_rate: number | null;
  e: number;
  compute_multiplier: number | null;
  paid_usd: number | null;
  baseline_usd: number;
  violations: number;
  tasks_with_violation: number;
  cache_hit_rate: number | null;
}

// One row of bench/sample_results/reference-run/learning_curve.csv (x axis: task order within an arm).
export interface CurvePoint {
  index: number;
  task: string;
  phase: string;
  e_cumulative: number;
  e_window: number;
  /** Review decisions made so far (rule-learning arm only). */
  rules_learned: number | null;
  /** Paths waiting for a decision after this task (rule-learning arm only). */
  review_pending: number | null;
}

export interface BenchEvidence {
  source: string;
  tasks: number;
  upstream: string;
  arms: BenchArm[];
  /** Per-task series by arm key; null when learning_curve.csv is missing. */
  curve: Record<string, CurvePoint[]> | null;
}
