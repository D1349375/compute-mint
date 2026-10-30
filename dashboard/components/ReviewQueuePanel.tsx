"use client";

import { useState } from "react";

import type { Strings } from "@/lib/i18n";
import type { ReviewItem, ReviewQueue } from "@/lib/types";
import { decide } from "@/lib/useGateway";

const CHOICES = ["public", "own_ip", "confidential"] as const;
const LABEL_CLASS: Record<string, string> = {
  PUBLIC: "lbl-public", OWN_IP: "lbl-own", CONFIDENTIAL: "lbl-conf", FLOOR: "lbl-floor",
};

// One decision settles every pending path its pattern covers (Policy.decide), so paths that share a
// suggested pattern are shown, and decided, together.
interface Group {
  pattern: string;
  items: ReviewItem[];
  hits: number;
}

function group(pending: ReviewItem[]): Group[] {
  const by = new Map<string, Group>();
  for (const item of pending) {
    const g = by.get(item.suggested_pattern) ?? { pattern: item.suggested_pattern, items: [], hits: 0 };
    g.items.push(item);
    g.hits = Math.max(g.hits, item.hits);   // a request can hold back several paths: do not add up
    by.set(item.suggested_pattern, g);
  }
  return [...by.values()];
}

function Item({ group: g, t, onDecided }: { group: Group; t: Strings; onDecided: () => void }) {
  const item = g.items[0];
  const [pattern, setPattern] = useState(g.pattern);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function choose(label: string) {
    setBusy(true);
    setError(false);
    try {
      await decide(item.id, label, pattern.trim() || item.suggested_pattern);
      onDecided();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="review-item">
      <div className="review-path">
        <div className="paths">
          {g.items.map((i) => (
            <code key={i.id}>{i.path}</code>
          ))}
        </div>
        <span className="hits">{t.heldBack(g.hits)}</span>
      </div>
      <div className="review-actions">
        <label className="pattern">
          <span className="sr-only">{t.pattern}</span>
          <input value={pattern} onChange={(e) => setPattern(e.target.value)} spellCheck={false} aria-label={t.pattern} />
        </label>
        {CHOICES.map((c) => (
          <button key={c} className={`btn ${c === "public" ? "primary" : ""}`} disabled={busy} onClick={() => choose(c)}>
            {t[c]}
          </button>
        ))}
      </div>
      {error ? <p className="error">POST /v1/review/{item.id} failed</p> : null}
    </li>
  );
}

export default function ReviewQueuePanel({ review, t, onDecided }: {
  review: ReviewQueue | null; t: Strings; onDecided: () => void;
}) {
  const pending = review?.pending ?? [];
  const groups = group(pending);
  const rules = review?.rules ?? [];
  return (
    <article className="card review">
      <div className="card-head">
        <div>
          <h2>
            {t.reviewTitle} <span className="count">{pending.length}</span>
          </h2>
          <p className="sub">{t.reviewSub}</p>
        </div>
      </div>
      {pending.length === 0 ? (
        <p className="empty">{t.noPending}</p>
      ) : (
        <ul className="review-list">
          {groups.map((g) => (
            <Item key={g.pattern} group={g} t={t} onDecided={onDecided} />
          ))}
        </ul>
      )}
      <h3>{t.rules}</h3>
      {rules.length === 0 ? (
        <p className="empty">{t.noRules}</p>
      ) : (
        <ul className="rules">
          {rules.map((r) => (
            <li key={r.pattern}>
              <code>{r.pattern}</code>
              <span className={`lbl ${LABEL_CLASS[r.label] ?? ""}`}>{r.label}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="hint">{t.replayHint}</p>
    </article>
  );
}
