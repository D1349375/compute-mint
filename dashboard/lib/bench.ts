import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BenchArm, BenchEvidence, CurvePoint } from "./types";

// The arms the demo shows, in the order of bench/README.md. Extra arms stay in results.json.
const ARMS = ["standard", "naive", "mint", "mint_broker", "mint_learn", "oracle"];

export const BENCH_RESULTS =
  process.env.BENCH_RESULTS ??
  path.join(process.cwd(), "..", "bench", "sample_results", "reference-run", "results.json");

type RawSummary = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

// The arms drawn on the flywheel chart (keys of learning_curve.csv).
const CURVE_ARMS = ["standard", "mint", "mint_learn", "oracle"];

/** learning_curve.csv sits next to results.json; rows of arms the chart does not draw are dropped. */
async function loadCurve(file: string): Promise<Record<string, CurvePoint[]> | null> {
  let text: string;
  try {
    text = await readFile(/*turbopackIgnore: true*/ path.join(path.dirname(file), "learning_curve.csv"), "utf-8");
  } catch {
    return null;
  }
  const [head, ...lines] = text.trim().split(/\r?\n/);
  const col = Object.fromEntries(head.split(",").map((h, i) => [h, i]));
  const curve: Record<string, CurvePoint[]> = {};
  for (const line of lines) {
    const c = line.split(",");
    const arm = c[col.arm];
    if (!CURVE_ARMS.includes(arm)) continue;
    const opt = (k: string) => (c[col[k]] ? num(Number(c[col[k]])) : null);
    (curve[arm] ??= []).push({
      index: Number(c[col.task_index]),
      task: c[col.task_id],
      phase: c[col.phase],
      e_cumulative: Number(c[col.e_cumulative]),
      e_window: Number(c[col.e_window]),
      rules_learned: opt("rules_learned"),
      review_pending: opt("review_pending"),
    });
  }
  return CURVE_ARMS.every((a) => curve[a]?.length) ? curve : null;
}

/** Reads only `summaries` and `options` of a bench run; returns null when the file is missing. */
export async function loadBench(file = BENCH_RESULTS): Promise<BenchEvidence | null> {
  let raw: { summaries?: Record<string, RawSummary>; options?: Record<string, unknown> };
  try {
    // Outside the app on purpose (the repo's bench folder): keep it out of output tracing.
    raw = JSON.parse(await readFile(/*turbopackIgnore: true*/ file, "utf-8"));
  } catch {
    return null;
  }
  const summaries = raw.summaries ?? {};
  const arms: BenchArm[] = ARMS.filter((a) => summaries[a]).map((a) => {
    const s = summaries[a];
    return {
      arm: a,
      title: String(s.title ?? a),
      executed: s.executed !== false,
      passed: num(s.passed),
      tasks: num(s.tasks) ?? 0,
      pass_rate: num(s.pass_rate),
      e: num(s.e) ?? 0,
      compute_multiplier: num(s.compute_multiplier),
      paid_usd: num(s.paid_usd),
      baseline_usd: num(s.baseline_standard_usd) ?? 0,
      violations: num(s.violations) ?? 0,
      tasks_with_violation: num(s.tasks_with_violation) ?? 0,
      cache_hit_rate: num(s.cache_hit_rate),
    };
  });
  return {
    source: path.relative(path.join(process.cwd(), ".."), file).replaceAll("\\", "/"),
    tasks: arms[0]?.tasks ?? 0,
    upstream: String(raw.options?.upstream ?? "unknown"),
    arms,
    curve: await loadCurve(file),
  };
}
