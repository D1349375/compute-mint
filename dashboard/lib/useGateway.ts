"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { RequestPage, RequestRow, ReviewMark, ReviewQueue, SessionRow, Status, Summary } from "./types";

const POLL_MS = 4000;
// The timeline and lane mix are drawn from the newest rows; the gateway caps a page at 500.
const TIMELINE_ROWS = 500;

export interface GatewayData {
  status: Status | null;
  summary: Summary | null;
  page: RequestPage | null;
  sessions: SessionRow[];
  review: ReviewQueue | null;
  /** Rule-count growth seen while the page was open, oldest first. */
  marks: ReviewMark[];
  online: boolean | null;
  updatedAt: number | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api/gw/${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export function useGateway(session: string | null) {
  const [data, setData] = useState<GatewayData>({
    status: null, summary: null, page: null, sessions: [], review: null, marks: [], online: null, updatedAt: null,
  });
  const seq = useRef(0);
  const rules = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    const q = session ? `session=${encodeURIComponent(session)}&` : "";
    try {
      const [status, summary, page, sessions, review] = await Promise.all([
        get<Status>("status"),
        get<Summary>(`ledger/summary${session ? `?session=${encodeURIComponent(session)}` : ""}`),
        get<RequestPage>(`ledger/requests?${q}limit=${TIMELINE_ROWS}`),
        get<{ sessions: SessionRow[] }>("ledger/sessions"),
        get<ReviewQueue>("review"),
      ]);
      if (mine !== seq.current) return;
      const now = review.rules.length;
      const added = rules.current == null ? 0 : now - rules.current;
      rules.current = now;
      setData((d) => ({
        status, summary, page, sessions: sessions.sessions, review,
        marks: added > 0 ? [...d.marks, { ts: Date.now() / 1000, rules: now, added }] : d.marks,
        online: true, updatedAt: Date.now(),
      }));
    } catch {
      if (mine !== seq.current) return;
      setData((d) => ({ ...d, online: false, updatedAt: Date.now() }));
    }
  }, [session]);

  useEffect(() => {
    // Polling an external system: the state update happens in the fetch callback.
    void refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return { data, refresh };
}

export async function decide(id: number, label: string, pattern: string): Promise<void> {
  const res = await fetch(`/api/gw/review/${id}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label, pattern }),
  });
  if (!res.ok) throw new Error(`review ${id}: ${res.status}`);
}

export async function loadRequest(id: number) {
  return get<RequestRow>(`ledger/requests/${id}`);
}
