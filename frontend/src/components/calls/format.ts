// Shared formatting helpers for the calls/* components.

export function formatDuration(sec: number) {
  if (!sec) return "0s";
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function formatDate(d: string) {
  try {
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return d;
  }
}

/** Accepts both the snake_case (billing.py) and legacy camelCase keys. */
export function callBilled(cost: any): number {
  return cost?.client_price_inr ?? cost?.clientPrice ?? 0;
}

export function callRatePerMin(cost: any): number | string {
  return cost?.client_bill_per_min ?? cost?.client_rate_per_min
    ?? cost?.billPerMin ?? cost?.clientRatePerMin ?? "-";
}
