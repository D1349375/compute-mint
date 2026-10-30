import type { Strings } from "@/lib/i18n";
import type { Status } from "@/lib/types";

export default function BillingBanner({ status, t }: { status: Status | null; t: Strings }) {
  if (!status) return <section className="card billing skeleton" aria-busy />;
  const credits = status.billing === "credits";
  const fallback = !credits
    ? t.fallbackStandard
    : status.local_model
      ? t.fallbackLocal(status.local_model)
      : t.fallbackHeld;
  return (
    <section className={`card billing ${credits ? "is-credits" : "is-paid"}`}>
      <div className="mode">
        <span className="eyebrow">{t.billingMode}</span>
        <span className="mode-pill">
          <code>CM_BILLING={status.billing}</code>
          <strong>{credits ? t.credits : t.paid}</strong>
        </span>
      </div>
      <p className="why">{credits ? t.creditsWhy : t.paidWhy}</p>
      <div className="route">
        <span className="eyebrow">{t.fallback}</span>
        <strong>{fallback}</strong>
      </div>
    </section>
  );
}
