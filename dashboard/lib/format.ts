/** Dollars with enough digits to stay readable when amounts are tiny (a few cents per session). */
export function usd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const digits = a === 0 ? 2 : a >= 100 ? 0 : a >= 1 ? 2 : a >= 0.01 ? 4 : 5;
  return `${v < 0 ? "−" : ""}$${a.toFixed(digits)}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function times(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(v >= 10 ? 1 : 2)}×`;
}

export function int(v: number): string {
  return v.toLocaleString("en-US");
}

export function clock(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
