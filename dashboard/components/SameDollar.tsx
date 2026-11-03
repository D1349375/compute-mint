"use client";

import { useEffect, useState } from "react";

import type { Strings } from "@/lib/i18n";
import { times } from "@/lib/format";
import type { BenchArm, BenchEvidence } from "@/lib/types";

const GROW_MS = 1400;

/** Counts from 0 to `value` once, unless the viewer asked for reduced motion. */
function useCountUp(value: number): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const id = requestAnimationFrame(() => setV(value));
      return () => cancelAnimationFrame(id);
    }
    let id = 0;
    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / GROW_MS);
      setV(value * (1 - (1 - k) ** 3));
      if (k < 1) id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [value]);
  return v;
}

const pick = (bench: BenchEvidence, key: string): BenchArm | undefined => bench.arms.find((a) => a.arm === key);

export default function SameDollar({ bench, t }: { bench: BenchEvidence | null; t: Strings }) {
  const std = bench && pick(bench, "standard");
  const mint = bench && pick(bench, "mint_learn");
  const ok = !!(bench && std && mint && std.compute_multiplier && mint.compute_multiplier && std.paid_usd && mint.paid_usd);
  // Multipliers come from the bench summaries (counterfactual ÷ paid); tasks per $1 is passed ÷ paid.
  const stdX = ok ? std.compute_multiplier! : 0;
  const mintX = ok ? mint.compute_multiplier! : 0;
  const stdTasks = ok ? (std.passed ?? 0) / std.paid_usd! : 0;
  const mintTasks = ok ? (mint.passed ?? 0) / mint.paid_usd! : 0;
  const countX = useCountUp(mintX);
  const countTasks = useCountUp(mintTasks);
  if (!bench || !ok) return null;
  const rows = [
    { key: "std", label: t.dollarStandard, x: stdX, shownX: stdX, tasks: stdTasks, arm: std! },
    { key: "mint", label: t.dollarMint, x: mintX, shownX: countX, tasks: countTasks, arm: mint! },
  ];
  return (
    <section className="card dollar">
      <div className="card-head">
        <div>
          <h2>{t.dollarTitle}</h2>
          <p className="sub">{t.dollarSub(bench.tasks, bench.upstream)}</p>
        </div>
        <span className="tag">{t.flyMock(bench.upstream)}</span>
      </div>
      <div className="dollar-rows">
        {rows.map((r, i) => (
          <div key={r.key} className={`dollar-row${r.key === "mint" ? " is-mint" : ""}`}>
            <div className="dollar-label">
              <span>{r.label}</span>
              <span className="muted">{t.dollarAccept(r.arm.passed ?? 0, r.arm.tasks)}</span>
            </div>
            <div className="dollar-track">
              <span className="dollar-fill" style={{ width: `${(r.x / mintX) * 100}%`, animationDelay: `${i * 0.25}s` }} />
              <span className="dollar-val">{times(r.shownX)}</span>
            </div>
            <div className="dollar-tasks">{t.dollarTasks(Math.round(r.tasks))}</div>
          </div>
        ))}
      </div>
      <p className="dollar-more">{t.dollarMore(Math.round((mintX / stdX - 1) * 100))}</p>
    </section>
  );
}
