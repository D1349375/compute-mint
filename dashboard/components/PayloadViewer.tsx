"use client";

import { Fragment, useEffect, useState } from "react";

import { clock } from "@/lib/format";
import type { Strings } from "@/lib/i18n";
import type { RequestRow } from "@/lib/types";
import { loadRequest } from "@/lib/useGateway";

// Same shape as gateway/compute_mint/vault.py PLACEHOLDER.
const PLACEHOLDER = /⟨[A-Z_]+_\d+⟩/g;
const HAS_PLACEHOLDER = /⟨[A-Z_]+_\d+⟩/;

interface Msg {
  role: string;
  content?: string | { type?: string; text?: string }[] | null;
  tool_calls?: { function?: { name?: string; arguments?: string } }[];
}

function Marked({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    parts.push(text.slice(last, m.index));
    parts.push(
      <mark key={m.index} className="ph" title="masked: the original value stayed on this machine">
        <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden>
          <path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2h.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm1.5 0h4V5a2 2 0 1 0-4 0z" fill="currentColor" />
        </svg>
        {m[0]}
      </mark>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

function textOf(m: Msg): string {
  if (typeof m.content === "string") return m.content;
  if (Array.isArray(m.content)) return m.content.map((p) => p.text ?? "").join("\n");
  return "";
}

function Message({ m, t }: { m: Msg; t: Strings }) {
  const [open, setOpen] = useState(false);
  const text = textOf(m);
  const collapsible = m.role === "system" || text.length > 900;
  const hasPh = HAS_PLACEHOLDER.test(text);
  const showText = !collapsible || open || hasPh;
  return (
    <div className={`msg role-${m.role}`}>
      <div className="msg-head">
        <span className="role">{m.role}</span>
        {collapsible && !hasPh ? (
          <button className="link" onClick={() => setOpen(!open)}>
            {m.role === "system" ? t.systemPrompt : ""} {text.length.toLocaleString()} {t.chars} · {open ? t.hide : t.showAll}
          </button>
        ) : null}
      </div>
      {text && showText ? (
        <pre className="msg-body"><Marked text={text} /></pre>
      ) : null}
      {(m.tool_calls ?? []).map((c, i) => (
        <pre key={i} className="msg-body call">
          <span className="muted">{t.toolCall} </span>
          {c.function?.name}(<Marked text={c.function?.arguments ?? ""} />)
        </pre>
      ))}
    </div>
  );
}

export default function PayloadViewer({ id, t }: { id: number | null; t: Strings }) {
  const [row, setRow] = useState<RequestRow | null>(null);

  useEffect(() => {
    let live = true;
    if (id == null) return;
    loadRequest(id).then((r) => live && setRow(r)).catch(() => live && setRow(null));
    return () => {
      live = false;
    };
  }, [id]);

  const current = row && row.id === id ? row : null;
  let messages: Msg[] = [];
  try {
    messages = current?.sent_payload ? (JSON.parse(current.sent_payload) as Msg[]) : [];
  } catch {
    messages = [];
  }
  const found = [...new Set((current?.sent_payload ?? "").match(PLACEHOLDER) ?? [])];

  return (
    <article className="card payload">
      <div className="card-head">
        <div>
          <h2>{t.leftTitle}</h2>
          <p className="sub">{t.leftSub}</p>
        </div>
        {current ? (
          <div className="ph-count">
            <span className="big">{found.length}</span> {t.placeholders}
          </div>
        ) : null}
      </div>
      {!current ? (
        <p className="empty">{t.noPayload}</p>
      ) : (
        <>
          <div className="payload-meta">
            <span className="chip lane-contributor"><span className="sw" aria-hidden />{current.model}</span>
            <span>{t.request} #{current.id}</span>
            <span className="muted">{current.session} · {clock(current.ts)}</span>
            {found.length ? (
              <span className="ph-list">
                {found.map((p) => (
                  <Fragment key={p}><Marked text={p} /> </Fragment>
                ))}
              </span>
            ) : null}
          </div>
          <div className="messages">
            {messages.map((m, i) => (
              <Message key={`${current.id}-${i}`} m={m} t={t} />
            ))}
          </div>
        </>
      )}
    </article>
  );
}
