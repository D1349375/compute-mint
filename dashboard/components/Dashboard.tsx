"use client";

import { useEffect, useMemo, useState } from "react";

import { STRINGS, type Lang } from "@/lib/i18n";
import type { BenchEvidence } from "@/lib/types";
import { useGateway } from "@/lib/useGateway";

import BenchPanel from "./BenchPanel";
import BillingBanner from "./BillingBanner";
import KpiRow from "./KpiRow";
import LaneMix from "./LaneMix";
import Logo from "./Logo";
import PayloadViewer from "./PayloadViewer";
import RequestTable from "./RequestTable";
import ReviewQueuePanel from "./ReviewQueuePanel";
import Timeline from "./Timeline";

const LANG_KEY = "cm-dashboard-lang";

export default function Dashboard({ bench }: { bench: BenchEvidence | null }) {
  const [lang, setLang] = useState<Lang>("en");
  const [session, setSession] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const { data, refresh } = useGateway(session);
  const t = STRINGS[lang];

  useEffect(() => {
    let wanted = new URLSearchParams(window.location.search).get("lang");
    try {
      wanted = wanted ?? localStorage.getItem(LANG_KEY);
    } catch {
      /* storage unavailable: keep the default */
    }
    // Restoring a per-viewer preference (?lang=zh or the last choice) after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (wanted === "en" || wanted === "zh") setLang(wanted);
  }, []);

  const switchLang = (l: Lang) => {
    setLang(l);
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {
      /* ignore */
    }
  };

  const rows = useMemo(() => data.page?.requests ?? [], [data.page]);
  // Default to the newest Contributor request that had something masked: the one worth showing.
  const shown = useMemo(() => {
    if (selected != null && rows.some((r) => r.id === selected && r.has_payload)) return selected;
    const masked = rows.find((r) => r.has_payload && r.masked_spans > 0);
    return (masked ?? rows.find((r) => r.has_payload))?.id ?? null;
  }, [rows, selected]);

  return (
    <div className="page">
      <header className="top">
        <div className="brand">
          <Logo />
          <div>
            <h1>Compute Mint</h1>
            <p className="tagline">{t.tagline}</p>
          </div>
        </div>
        <div className="controls">
          <span className={`conn ${data.online === false ? "off" : "on"}`}>
            <span className="dot" aria-hidden />
            {data.online === false ? t.offline : t.live}
            {data.updatedAt && data.online ? (
              <span className="muted">
                {" "}· {t.refreshed} {new Date(data.updatedAt).toLocaleTimeString("en-GB")}
              </span>
            ) : null}
          </span>
          <label className="select">
            <span className="sr-only">{t.session}</span>
            <select
              value={session ?? ""}
              onChange={(e) => {
                setSession(e.target.value || null);
                setSelected(null);
              }}
            >
              <option value="">{t.allSessions}</option>
              {data.sessions.map((s) => (
                <option key={s.session} value={s.session}>
                  {s.session} ({s.requests})
                </option>
              ))}
            </select>
          </label>
          <div className="seg" role="group" aria-label="Language">
            {(["en", "zh"] as Lang[]).map((l) => (
              <button key={l} className={lang === l ? "on" : ""} onClick={() => switchLang(l)}>
                {l === "en" ? "EN" : "中文"}
              </button>
            ))}
          </div>
        </div>
      </header>

      {data.online === false && (
        <div className="notice" role="status">
          <strong>{t.offline}.</strong> {t.offlineHelp}
        </div>
      )}

      <BillingBanner status={data.status} t={t} />
      <KpiRow summary={data.summary} t={t} />

      <section className="grid two-one">
        <LaneMix rows={rows} lang={lang} t={t} />
        <Timeline rows={rows} lang={lang} t={t} onPick={setSelected} />
      </section>

      <section className="grid halves">
        <PayloadViewer id={shown} t={t} />
        <ReviewQueuePanel review={data.review} t={t} onDecided={refresh} />
      </section>

      <RequestTable rows={rows} lang={lang} t={t} selected={shown} onPick={setSelected} />
      <BenchPanel bench={bench} t={t} />

      <footer className="foot">{t.footer}</footer>
    </div>
  );
}
