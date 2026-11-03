"use client";

import { useEffect, useRef, useState } from "react";

import { clock, usd } from "@/lib/format";
import { LANE_NAMES, type Lang, type Strings } from "@/lib/i18n";
import { LANES, type RequestRow } from "@/lib/types";

const ROW_H = 46;
const PAD = { left: 112, right: 20, top: 8, bottom: 30 };

export default function Timeline({ rows, lang, t, onPick }: {
  rows: RequestRow[]; lang: Lang; t: Strings; onPick: (id: number) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<RequestRow | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(280, el.clientWidth));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const height = PAD.top + ROW_H * LANES.length + PAD.bottom;
  const ts = rows.map((r) => r.ts);
  const t0 = ts.length ? Math.min(...ts) : 0;
  const t1 = ts.length ? Math.max(...ts) : 1;
  const span = Math.max(t1 - t0, 60);
  const plotW = width - PAD.left - PAD.right;
  const x = (v: number) => PAD.left + ((v - t0) / span) * plotW;
  const y = (lane: string) => PAD.top + ROW_H * LANES.indexOf(lane as never) + ROW_H / 2;
  const ticks = Array.from({ length: 5 }, (_, i) => t0 + (span * i) / 4);

  return (
    <article className="card">
      <h2>{t.timeline}</h2>
      <p className="sub">{t.timelineSub}</p>
      <div className="timeline" ref={box} onMouseLeave={() => setHover(null)}>
        <svg width={width} height={height} role="img" aria-label={t.timeline}>
          {LANES.map((l, i) => (
            <g key={l}>
              <rect x={PAD.left} y={PAD.top + i * ROW_H + 4} width={plotW} height={ROW_H - 8} rx={8} className="swimlane" />
              <text x={PAD.left - 14} y={y(l) + 5} textAnchor="end" className="axis-label">{LANE_NAMES[lang][l]}</text>
            </g>
          ))}
          {ticks.map((v) => (
            <text key={v} x={x(v)} y={height - 8} textAnchor="middle" className="axis-tick">
              {clock(v).slice(0, 5)}
            </text>
          ))}
          {rows.map((r) => (
            <circle
              key={r.id}
              cx={x(r.ts)}
              cy={y(r.lane)}
              r={hover?.id === r.id ? 9 : 7}
              className={`dot lane-${r.lane}${r.has_payload ? " pickable" : ""}`}
              onMouseEnter={() => setHover(r)}
              onClick={() => r.has_payload && onPick(r.id)}
            />
          ))}
        </svg>
        {hover && (
          <div className="tip" style={{ left: Math.max(0, Math.min(x(hover.ts) + 12, width - 300)), top: y(hover.lane) + 14 }}>
            <div className="tip-head">
              <strong>{LANE_NAMES[lang][hover.lane]}</strong>
              <span className="muted">#{hover.id} · {clock(hover.ts)}</span>
            </div>
            <div className="tip-session">{hover.session}</div>
            <div className="tip-reason">{hover.reason}</div>
            <div className="muted">
              {usd(hover.cost)} · {t.cf} {usd(hover.counterfactual)}
              {hover.masked_spans ? ` · ${t.masked} ${hover.masked_spans}` : ""}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
