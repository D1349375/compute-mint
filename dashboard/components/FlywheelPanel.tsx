"use client";

import { useState } from "react";

import { clock, pct } from "@/lib/format";
import { LANE_NAMES, type Lang, type Strings } from "@/lib/i18n";
import type { BenchEvidence, RequestRow, ReviewMark, ReviewQueue } from "@/lib/types";
import { useBoxWidth } from "@/lib/useBoxWidth";

import BenchCurve from "./BenchCurve";

const PAD = { left: 52, right: 64, top: 30, bottom: 30 };
const STRIP_H = 22;
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1];

interface Point {
  row: RequestRow;
  e: number;
}

/** Cumulative e = tokens served by Contributor ÷ all tokens (the gateway's `contributable_token_share`), request by request. */
function cumulative(rows: RequestRow[]): Point[] {
  const sorted = [...rows].sort((a, b) => a.ts - b.ts || a.id - b.id);
  let contributor = 0;
  let all = 0;
  return sorted.map((row) => {
    const tokens = row.prompt_tokens + row.completion_tokens;
    all += tokens;
    if (row.lane === "contributor") contributor += tokens;
    return { row, e: all ? contributor / all : 0 };
  });
}

function LiveCurve({ rows, total, review, marks, lang, t }: {
  rows: RequestRow[]; total: number; review: ReviewQueue | null; marks: ReviewMark[]; lang: Lang; t: Strings;
}) {
  const [box, width] = useBoxWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pts = cumulative(rows);
  const n = pts.length;
  if (n < 2) return <p className="empty">{t.liveEmpty}</p>;

  const compact = width < 560;
  const plotH = compact ? 200 : 250;
  const height = PAD.top + plotH + 10 + STRIP_H + PAD.bottom;
  const plotW = width - PAD.left - PAD.right;
  const x = (i: number) => PAD.left + (i / (n - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - v * plotH;
  const stripY = PAD.top + plotH + 10 + STRIP_H / 2;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.e).toFixed(1)}`).join(" ");
  const dot = Math.max(1.5, Math.min(5, (plotW / n) * 0.42));
  // A decision sits between the last request before it and the first one after it.
  const markX = (m: ReviewMark) => {
    const before = pts.filter((p) => p.row.ts <= m.ts).length;
    return x(Math.max(0, Math.min(before - 0.5, n - 1)));
  };
  const last = pts[n - 1];

  const pick = (clientX: number, rect: DOMRect) => {
    // rect is in screen pixels, the plot in CSS pixels; they differ under the ?present=1 zoom.
    const px = (clientX - rect.left) * (width / rect.width);
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / plotW) * (n - 1)))));
  };

  return (
    <>
      <p className="sub">{t.liveSub(n)}</p>
      <div className="fly-box" ref={box} onMouseLeave={() => setHover(null)}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${t.flyTitle}: e ${pct(last.e)} ${t.liveRules(review?.rules.length ?? 0, review?.pending.length ?? 0)}`}
          onMouseMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
          onTouchStart={(e) => pick(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
        >
          {Y_TICKS.map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} className="grid-line" />
              <text x={PAD.left - 10} y={y(v) + 4} textAnchor="end" className="axis-tick">
                {Math.round(v * 100)}%
              </text>
            </g>
          ))}

          <path d={path} pathLength={1} fill="none" stroke="#0866ff" strokeWidth={4} strokeLinejoin="round" strokeLinecap="round" className="curve-line" />
          <text x={width - PAD.right + 8} y={y(last.e) + 4} className="end-label" fill="#0866ff">
            {pct(last.e)}
          </text>

          {marks.map((m) => (
            <g key={m.ts}>
              <line x1={markX(m)} x2={markX(m)} y1={PAD.top - 6} y2={PAD.top + plotH + 10 + STRIP_H} className="mark-line" />
              <text x={markX(m)} y={PAD.top - 10} textAnchor="middle" className="band-label">
                {t.liveMark(m.added)}
              </text>
            </g>
          ))}

          {pts.map((p, i) => (
            <circle key={p.row.id} cx={x(i)} cy={stripY} r={dot} className={`lane-dot lane-${p.row.lane}`} />
          ))}
          <text x={PAD.left} y={height - 8} textAnchor="middle" className="axis-tick">1</text>
          <text x={width - PAD.right} y={height - 8} textAnchor="middle" className="axis-tick">{n}</text>

          {hover != null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={stripY + 8} className="hover-line" />
              <circle cx={x(hover)} cy={y(pts[hover].e)} r={4.5} fill="#0866ff" stroke="#fff" strokeWidth={2} />
            </g>
          )}
        </svg>
        <div className="fly-axis-x">{t.liveAxisX} →</div>
        {hover != null && (
          <div className="tip fly-tip" style={{ left: Math.min(Math.max(0, x(hover) + 14), width - 250), top: PAD.top + 28 }}>
            <div className="muted">{t.liveTip(hover + 1, clock(pts[hover].row.ts))}</div>
            <div className="fly-tip-row">
              <span>{LANE_NAMES[lang][pts[hover].row.lane]}</span>
              <span className="muted">#{pts[hover].row.id}</span>
            </div>
            <div className="fly-tip-row">
              <span>{t.liveE}</span>
              <strong>{pct(pts[hover].e)}</strong>
            </div>
          </div>
        )}
      </div>
      <p className="fly-note">
        <strong>{t.liveRules(review?.rules.length ?? 0, review?.pending.length ?? 0)}</strong>
        {total > n ? ` · ${t.liveTruncated(n, total)}` : ""}
        {marks.length === 0 ? ` · ${t.liveNoMarks}` : ""}
      </p>
    </>
  );
}

export default function FlywheelPanel({ bench, rows, total, review, marks, lang, t }: {
  bench: BenchEvidence | null; rows: RequestRow[]; total: number; review: ReviewQueue | null; marks: ReviewMark[];
  lang: Lang; t: Strings;
}) {
  const [tab, setTab] = useState<"live" | "bench">("live");
  return (
    <section className="card flywheel">
      <div className="card-head">
        <h2>{t.flyTitle}</h2>
        <div className="seg" role="tablist" aria-label={t.flyTitle}>
          {(["live", "bench"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
              {k === "live" ? t.flyTabLive : t.flyTabBench}
            </button>
          ))}
        </div>
      </div>
      {tab === "live" ? (
        <LiveCurve rows={rows} total={total} review={review} marks={marks} lang={lang} t={t} />
      ) : (
        <BenchCurve bench={bench} t={t} />
      )}
    </section>
  );
}
