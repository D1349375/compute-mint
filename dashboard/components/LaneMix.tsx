import { int, pct } from "@/lib/format";
import { LANE_NAMES, LANE_NOTES, type Lang, type Strings } from "@/lib/i18n";
import { LANES, type Lane, type RequestRow } from "@/lib/types";

function Stack({ label, counts, total, lang, fmt }: {
  label: string; counts: Record<Lane, number>; total: number; lang: Lang; fmt: (n: number) => string;
}) {
  return (
    <div className="stack">
      <div className="stack-head">
        <span>{label}</span>
        <span className="muted">{fmt(total)}</span>
      </div>
      <div className="stack-bar" role="img"
        aria-label={LANES.map((l) => `${LANE_NAMES[lang][l]} ${counts[l]}`).join(", ")}>
        {LANES.filter((l) => counts[l] > 0).map((l) => (
          <span key={l} className={`seg-fill lane-${l}`} style={{ flexGrow: counts[l] }}
            title={`${LANE_NAMES[lang][l]}: ${fmt(counts[l])} (${pct(total ? counts[l] / total : 0)})`} />
        ))}
      </div>
    </div>
  );
}

export default function LaneMix({ rows, lang, t }: { rows: RequestRow[]; lang: Lang; t: Strings }) {
  const req = { contributor: 0, standard: 0, local: 0, held: 0 } as Record<Lane, number>;
  const tok = { ...req };
  for (const r of rows) {
    req[r.lane] += 1;
    tok[r.lane] += r.prompt_tokens + r.completion_tokens;
  }
  const nReq = rows.length;
  const nTok = LANES.reduce((a, l) => a + tok[l], 0);
  return (
    <article className="card">
      <h2>{t.laneMix}</h2>
      <Stack label={t.byRequests} counts={req} total={nReq} lang={lang} fmt={int} />
      <Stack label={t.byTokens} counts={tok} total={nTok} lang={lang} fmt={int} />
      <ul className="legend">
        {LANES.map((l) => (
          <li key={l}>
            <span className={`sw lane-${l}`} aria-hidden />
            <span className="legend-name">{LANE_NAMES[lang][l]}</span>
            <span className="legend-val">{int(req[l])}</span>
            <span className="legend-pct">{pct(nReq ? req[l] / nReq : 0, 0)}</span>
            <span className="legend-note">{LANE_NOTES[lang][l]}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}
