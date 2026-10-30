import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BenchArm, BenchEvidence } from "./types";

// The arms the demo shows, in the order of bench/README.md. Extra arms stay in results.json.
const ARMS = ["standard", "naive", "mint", "mint_broker", "mint_learn", "oracle"];

export const BENCH_RESULTS =
  process.env.BENCH_RESULTS ??
  path.join(process.cwd(), "..", "bench", "sample_results", "reference-run", "results.json");

type RawSummary = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

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
  };
}
