// Shared wallet/billing shapes for the billing/* components.

export interface Tx {
  ts: string;
  kind: string;
  amount: number;
  note?: string;
}

/** "26 Sep, 03:41 PM" style, robust to the server's raw ts string. */
export function formatTxDate(ts: string): string {
  try {
    const d = new Date(ts.replace(/-/g, "/").replace(" ", "T") || ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}
