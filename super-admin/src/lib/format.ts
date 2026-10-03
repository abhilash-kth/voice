// Small display helpers shared by every admin page.
// All guards are defensive: backend fields may be "" or missing.

export function fmtDateTime(v: unknown): string {
  if (typeof v !== "string" || !v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("en-GB", { hour12: false });
}

export function fmtINR(n: number | null | undefined): string {
  return `₹${(n ?? 0).toFixed(2)}`;
}

export function shortId(id: string | null | undefined): string {
  return id ? `${id.slice(0, 8)}…` : "—";
}

export function fmtDuration(seconds: number | null | undefined): string {
  const s = Math.round(seconds ?? 0);
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function toNum(s: string): number {
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}
