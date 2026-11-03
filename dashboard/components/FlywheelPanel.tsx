"use client";

import { useEffect, useRef, useState } from "react";

import { pct } from "@/lib/format";
import type { Strings } from "@/lib/i18n";
import type { BenchEvidence, CurvePoint } from "@/lib/types";

// Drawn back to front; the rule-learning arm is the story, the others are its reference lines.
const SERIES = [
  { arm: "standard", color: "#64748b", width: 2, dash: "" },
  { arm: "mint", color: "#6aa2f8", width: 2.5, dash: "" },
  { arm: "oracle", color: "#1c2b33", width: 2, dash: "6 5" },
  { arm: "mint_learn", color: "#0866ff", width: 4, dash: "" },
];

const Y_MAX = 0.72;
const Y_TICKS = [0, 0.2, 0.4, 0.6];
const PAD = { left: 52, right: 64, top: 30, bottom: 30 };
const TRACK_H = 34;

export default function FlywheelPanel({ bench, t }: { bench: BenchEvidence | null; t: Strings }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(280, el.clientWidth));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const curve = bench?.curve;
  if (!bench || !curve) {
    return (
      <section className="card">
        <h2>{t.flyTitle}</h2>
        <p className="empty">{t.benchMissing}</p>
      </section>
    );
  }

  const n = curve.mint_learn.length;
  const learn = curve.mint_learn;
  // Decisions made during a task = growth of rules_learned. Each decision turns into one rule.
  const decisions = learn.map((p, i) => Math.max(0, (p.rules_learned ?? 0) - (learn[i - 1]?.rules_learned ?? 0)));
  const totalDecisions = learn[n - 1].rules_learned ?? 0;
  const maxDecisions = Math.max(...decisions, 1);
  // The task by which 90% of the decisions were made: where the reviewing effectively ends.
  const doneAt = learn.findIndex((p) => (p.rules_learned ?? 0) >= 0.9 * totalDecisions);
  const doneShare = Math.round(((learn[doneAt].rules_learned ?? 0) / totalDecisions) * 100);

  const compact = width < 560;
  const plotH = compact ? 230 : 290;
  const height = PAD.top + plotH + 8 + TRACK_H + PAD.bottom;
  const plotW = width - PAD.left - PAD.right;
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * plotW : 0);
  const y = (v: number) => PAD.top + plotH - (v / Y_MAX) * plotH;
  const trackTop = PAD.top + plotH + 8;
  const path = (pts: CurvePoint[]) =>
    pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.e_cumulative).toFixed(1)}`).join(" ");

  // End labels: push apart when two lines finish close together.
  const ends = SERIES.map((s) => ({ ...s, v: curve[s.arm][n - 1].e_cumulative, y: y(curve[s.arm][n - 1].e_cumulative) })).sort(
    (a, b) => a.y - b.y,
  );
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 17) ends[i].y = ends[i - 1].y + 17;

  const pick = (clientX: number, rect: DOMRect) => {
    // rect is in screen pixels, the plot in CSS pixels; they differ under the ?present=1 zoom.
    const px = (clientX - rect.left) * (width / rect.width);
    const i = Math.round(((px - PAD.left) / plotW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const final = learn[n - 1].e_cumulative;

  return (
    <section className="card flywheel">
      <div className="card-head">
        <div>
          <h2>{t.flyTitle}</h2>
          <p className="sub">{t.flySub(n, bench.upstream, totalDecisions)}</p>
        </div>
        <span className="tag">{t.flyMock(bench.upstream)}</span>
      </div>

      <ul className="fly-legend">
        {SERIES.slice()
          .reverse()
          .map((s) => (
            <li key={s.arm}>
              <svg width="30" height="10" aria-hidden>
                <line x1="1" x2="29" y1="5" y2="5" stroke={s.color} strokeWidth={s.width} strokeDasharray={s.dash} strokeLinecap="round" />
              </svg>
              {t.flyArm[s.arm]}
            </li>
          ))}
      </ul>

      <div className="fly-box" ref={box} onMouseLeave={() => setHover(null)}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${t.flyTitle}: ${SERIES.map((s) => `${t.flyArm[s.arm]} ${pct(curve[s.arm][n - 1].e_cumulative)}`).join(", ")}`}
          onMouseMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
          onTouchStart={(e) => pick(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
        >
          {/* the stretch where most reviewing happens */}
          <rect x={x(0)} y={PAD.top} width={x(doneAt) - x(0)} height={plotH + 8 + TRACK_H} className="fly-band" />
          {Y_TICKS.map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} className="grid-line" />
              <text x={PAD.left - 10} y={y(v) + 4} textAnchor="end" className="axis-tick">
                {Math.round(v * 100)}%
              </text>
            </g>
          ))}
          <text x={PAD.left} y={PAD.top - 9} dx={6} className="band-label">
            {t.flyReviewBand(doneShare, totalDecisions, doneAt + 1)}
          </text>

          {SERIES.map((s, k) => (
            <path
              key={s.arm}
              d={path(curve[s.arm])}
              // The dashed line keeps real units so the dashes show; the solid ones draw themselves via pathLength 1.
              pathLength={s.dash ? undefined : 1}
              fill="none"
              stroke={s.color}
              strokeWidth={s.width}
              strokeLinejoin="round"
              strokeLinecap="round"
              className={`curve-line${s.dash ? " dashed" : ""}`}
              style={{ animationDelay: `${k * 0.18}s`, ...(s.dash ? { strokeDasharray: s.dash } : {}) }}
            />
          ))}

          {ends.map((e) => (
            <text key={e.arm} x={width - PAD.right + 8} y={e.y + 4} className="end-label" fill={e.color}>
              {pct(e.v)}
            </text>
          ))}

          {/* review decisions per task */}
          <text x={x(doneAt) + 14} y={trackTop + TRACK_H / 2 + 4} className="axis-tick">
            ◀ {t.flyReviews}: {totalDecisions}
          </text>
          {decisions.map((d, i) =>
            d > 0 ? (
              <rect
                key={i}
                x={x(i) - 3.5}
                y={trackTop + TRACK_H - (d / maxDecisions) * TRACK_H}
                width={7}
                height={(d / maxDecisions) * TRACK_H}
                rx={2}
                className="review-bar"
              />
            ) : null,
          )}
          <line x1={PAD.left} x2={width - PAD.right} y1={trackTop + TRACK_H + 0.5} y2={trackTop + TRACK_H + 0.5} className="grid-line" />

          {[0, 9, 19, 29, n - 1].map((i) => (
            <text key={i} x={x(i)} y={height - 8} textAnchor="middle" className="axis-tick">
              {i + 1}
            </text>
          ))}

          {hover != null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={trackTop + TRACK_H} className="hover-line" />
              {SERIES.map((s) => (
                <circle key={s.arm} cx={x(hover)} cy={y(curve[s.arm][hover].e_cumulative)} r={4.5} fill={s.color} stroke="#fff" strokeWidth={2} />
              ))}
            </g>
          )}
        </svg>
        <div className="fly-axis-x">{t.flyAxisX} →</div>
        {hover != null && (
          <div className="tip fly-tip" style={{ left: Math.min(Math.max(0, x(hover) + 14), width - 250), top: PAD.top + 28 }}>
            <div className="muted">{t.flyTip(hover + 1, learn[hover].task)}</div>
            {SERIES.slice()
              .reverse()
              .map((s) => (
                <div key={s.arm} className="fly-tip-row">
                  <span>
                    <i style={{ background: s.color }} /> {t.flyArm[s.arm]}
                  </span>
                  <strong>{pct(curve[s.arm][hover].e_cumulative)}</strong>
                </div>
              ))}
            <div className="muted fly-tip-row">
              <span>{t.flyReviews}</span>
              <span>{learn[hover].rules_learned ?? 0}</span>
            </div>
          </div>
        )}
      </div>

      <p className="fly-note">
        <strong>
          {t.flyArm.mint} {pct(curve.mint[n - 1].e_cumulative)} → {t.flyArm.mint_learn} {pct(final)}
        </strong>{" "}
        · {t.flyNote}
      </p>
    </section>
  );
}
