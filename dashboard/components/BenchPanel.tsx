import { pct, times } from "@/lib/format";
import type { Strings } from "@/lib/i18n";
import type { BenchEvidence } from "@/lib/types";

export default function BenchPanel({ bench, t }: { bench: BenchEvidence | null; t: Strings }) {
  if (!bench) {
    return (
      <section className="card">
        <h2>{t.benchTitle}</h2>
        <p className="empty">{t.benchMissing}</p>
      </section>
    );
  }
  const maxE = Math.max(...bench.arms.map((a) => a.e), 0.01);
  return (
    <section className="card bench">
      <div className="card-head">
        <div>
          <h2>{t.benchTitle}</h2>
          <p className="sub">{t.benchSub(bench.tasks, bench.upstream)}</p>
        </div>
        <code className="source">{bench.source}</code>
      </div>
      <div className="table-wrap">
        <table className="bench-table">
          <thead>
            <tr>
              <th>{t.arm}</th>
              <th>{t.acceptance}</th>
              <th className="e-col">{t.e}</th>
              <th className="r">{t.computeX}</th>
              <th className="r">{t.canary}</th>
            </tr>
          </thead>
          <tbody>
            {bench.arms.map((a) => {
              const mint = a.arm.startsWith("mint") || a.arm === "oracle";
              return (
                <tr key={a.arm} className={a.arm === "mint_learn" ? "highlight" : ""}>
                  <td className="arm">{a.title}</td>
                  <td>
                    {a.executed && a.passed != null ? (
                      <span className="mono">
                        {a.passed}/{a.tasks} <span className="muted">({pct(a.pass_rate, 0)})</span>
                      </span>
                    ) : (
                      <span className="muted">{t.notExecuted}</span>
                    )}
                  </td>
                  <td className="e-col">
                    <div className="ebar">
                      <span className={`ebar-fill${mint ? " mint" : ""}`} style={{ width: `${(a.e / maxE) * 100}%` }} />
                      <span className="ebar-val">{pct(a.e)}</span>
                    </div>
                  </td>
                  <td className="r mono">{a.executed ? times(a.compute_multiplier) : "—"}</td>
                  <td className="r">
                    <span className={`canary ${a.violations === 0 ? "ok" : "bad"}`}>
                      {a.violations === 0 ? (
                        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
                          <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="2.2" fill="none" strokeLinecap="round" />
                        </svg>
                      ) : (
                        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
                          <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
                        </svg>
                      )}
                      {a.violations}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
