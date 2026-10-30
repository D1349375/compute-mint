import { int, pct, times, usd } from "@/lib/format";
import type { Strings } from "@/lib/i18n";
import type { Summary } from "@/lib/types";

export default function KpiRow({ summary, t }: { summary: Summary | null; t: Strings }) {
  if (!summary) return <section className="kpis skeleton" aria-busy />;
  const s = summary;
  const savedShare = s.counterfactual_usd > 0 ? s.saved_usd / s.counterfactual_usd : 0;
  const paidW = s.counterfactual_usd > 0 ? Math.max((s.spent_usd / s.counterfactual_usd) * 100, 0.8) : 0;
  const stayed = s.local_requests + s.held_requests;
  return (
    <section className="kpis">
      <article className="card kpi hero">
        <span className="eyebrow">{t.saved}</span>
        <div className="hero-num">
          {pct(savedShare, 0)}
          <span className="hero-usd">{usd(s.saved_usd)}</span>
        </div>
        <p className="sub">{t.vsStandard}</p>
        <div className="versus" aria-label={`${t.paidLabel} ${usd(s.spent_usd)}, ${t.counterfactual} ${usd(s.counterfactual_usd)}`}>
          <div className="vs-row">
            <span className="vs-label">{t.paidLabel}</span>
            <span className="vs-track">
              <span className="vs-bar paid" style={{ width: `${paidW}%` }} />
            </span>
            <span className="vs-val">{usd(s.spent_usd)}</span>
          </div>
          <div className="vs-row">
            <span className="vs-label">{t.counterfactual}</span>
            <span className="vs-track">
              <span className="vs-bar cf" style={{ width: s.counterfactual_usd > 0 ? "100%" : "0%" }} />
            </span>
            <span className="vs-val">{usd(s.counterfactual_usd)}</span>
          </div>
        </div>
      </article>
      <Kpi label={t.multiplier} value={times(s.effective_compute_multiplier)} sub={t.multiplierSub} accent />
      <Kpi label={t.eShare} value={pct(s.contributable_token_share)} sub={t.eSub} />
      <Kpi label={t.cacheHit} value={pct(s.cache_hit_rate)} sub={t.cacheSub} />
      <Kpi label={t.creditsUsed} value={usd(s.credits_usd)} sub={t.creditsSub} />
      <Kpi
        label={t.stayed}
        value={int(stayed)}
        unit={`/ ${int(s.requests)} ${t.requests}`}
        sub={t.stayedSub(s.local_requests, s.held_requests)}
      />
    </section>
  );
}

function Kpi({ label, value, sub, unit, accent }: { label: string; value: string; sub: string; unit?: string; accent?: boolean }) {
  return (
    <article className={`card kpi${accent ? " accent" : ""}`}>
      <span className="eyebrow">{label}</span>
      <div className="num">
        {value}
        {unit ? <span className="unit"> {unit}</span> : null}
      </div>
      <p className="sub">{sub}</p>
    </article>
  );
}
