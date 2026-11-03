"use client";

import { useEffect, useState } from "react";

import { cloudMultiplier } from "@/lib/compute";
import { times, usd } from "@/lib/format";
import type { Strings } from "@/lib/i18n";
import type { BenchEvidence, RequestRow, Summary } from "@/lib/types";

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

/**
 * Standard-priced cost against cost paid, from the live ledger and with the same definition as the KPI card
 * (local requests are not counted as free). The bench's multiplier for Mint with rule learning is a reference tick.
 */
export default function SameDollar({ summary, rows, bench, t }: {
  summary: Summary | null; rows: RequestRow[]; bench: BenchEvidence | null; t: Strings;
}) {
  const m = summary ? cloudMultiplier(summary, rows) : null;
  const x = m?.value ?? 0;
  const learn = bench?.arms.find((a) => a.arm === "mint_learn");
  const ref = learn?.compute_multiplier ?? null;
  const top = Math.max(x, ref ?? 0, 1);
  const shown = useCountUp(x);
  const note = m
    ? m.kind === "cloud"
      ? t.multiplierCloud(m.localRequests, usd(m.localCf))
      : m.kind === "truncated"
        ? t.multiplierTruncated
        : null
    : null;

  return (
    <section className="card dollar">
      <div className="card-head">
        <h2>{t.dollarTitle}</h2>
      </div>
      <p className="sub">{t.dollarSub}</p>
      {x > 0 ? (
        <>
          <div className="dollar-rows">
            <div className="dollar-row">
              <div className="dollar-label"><span>{t.dollarStandard}</span></div>
              <div className="dollar-track">
                <span className="dollar-fill" style={{ width: `${(1 / top) * 100}%` }} />
                <span className="dollar-val">{times(1)}</span>
              </div>
            </div>
            <div className="dollar-row is-mint">
              <div className="dollar-label"><span>{t.dollarMint}</span></div>
              <div className="dollar-track">
                <span className="dollar-fill" style={{ width: `${(x / top) * 100}%`, animationDelay: "0.25s" }} />
                <span className="dollar-val">{times(shown)}</span>
                {ref != null && ref > 0 && (
                  <span className="dollar-ref" style={{ left: `${(ref / top) * 100}%` }} title={t.dollarBenchNote(times(ref))}>
                    <i />
                    <b>{t.dollarBenchRef(times(ref), bench?.tasks ?? 0, bench?.upstream ?? "")}</b>
                  </span>
                )}
              </div>
            </div>
          </div>
          <p className="dollar-more">{t.dollarPaid(usd(1 / x))}</p>
          {ref != null && <p className="dollar-note">{t.dollarBenchNote(times(ref))}</p>}
          {note && <p className="dollar-note">{note}</p>}
        </>
      ) : (
        <p className="empty">{t.dollarNone}</p>
      )}
    </section>
  );
}
