"use client";

import { useState } from "react";

import { clock, int, usd } from "@/lib/format";
import type { Lang, Strings } from "@/lib/i18n";
import type { RequestRow } from "@/lib/types";

import LaneChip from "./LaneChip";

const PAGE = 12;

export default function RequestTable({ rows, lang, t, selected, onPick }: {
  rows: RequestRow[]; lang: Lang; t: Strings; selected: number | null; onPick: (id: number) => void;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const p = Math.min(page, pages - 1);
  const shown = rows.slice(p * PAGE, p * PAGE + PAGE);
  return (
    <section className="card">
      <div className="card-head">
        <h2>{t.tableTitle}</h2>
        <div className="pager">
          <button className="btn" disabled={p === 0} onClick={() => setPage(p - 1)}>{t.prev}</button>
          <span className="muted">{p + 1} {t.of} {pages}</span>
          <button className="btn" disabled={p >= pages - 1} onClick={() => setPage(p + 1)}>{t.next}</button>
        </div>
      </div>
      <div className="table-wrap">
        <table className="requests">
          <thead>
            <tr>
              <th>#</th>
              <th>{t.time}</th>
              <th>{t.session}</th>
              <th>{t.lane}</th>
              <th>{t.billing}</th>
              <th className="r">{t.tokens}</th>
              <th className="r">{t.masked}</th>
              <th className="r">{t.cost}</th>
              <th className="r">{t.cf}</th>
              <th>{t.reason}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr
                key={r.id}
                className={`${r.has_payload ? "pickable" : ""}${r.id === selected ? " selected" : ""}`}
                onClick={() => r.has_payload && onPick(r.id)}
              >
                <td className="muted">{r.id}</td>
                <td className="mono">{clock(r.ts)}</td>
                <td className="mono session">{r.session}</td>
                <td><LaneChip lane={r.lane} lang={lang} /></td>
                <td><span className={`bill bill-${r.billing}`}>{r.billing}</span></td>
                <td className="r mono">
                  {int(r.prompt_tokens + r.completion_tokens)}
                  <span className="muted"> ({int(r.cached_tokens)})</span>
                </td>
                <td className="r mono">{r.masked_spans || ""}</td>
                <td className="r mono">{usd(r.cost)}</td>
                <td className="r mono muted">{usd(r.counterfactual)}</td>
                <td className="reason">{r.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
