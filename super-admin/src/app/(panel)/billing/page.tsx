"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import RateCalculator from "@/components/RateCalculator";
import { getBilling, updateBilling, type BillingConfig } from "@/lib/billing";
import { fmtINR, toNum } from "@/lib/format";

/**
 * Per-minute pricing knobs only. Everything monthly (agent plans, concurrency
 * lines, telephony rent, KB packs) lives on the Plans page.
 * Formula: customer ₹/min = Σ model prices (Models page) + server cost,
 * floored at the per-mode minimum and never below real cost × (1+margin).
 */
export default function BillingPage() {
  const [cfg, setCfg] = useState<BillingConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const [serverCost, setServerCost] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [margin, setMargin] = useState("");
  const [assistMin, setAssistMin] = useState("");
  const [announceMin, setAnnounceMin] = useState("");
  const [assistMinSecs, setAssistMinSecs] = useState("");
  const [announceMinSecs, setAnnounceMinSecs] = useState("");
  const [topups, setTopups] = useState("");

  const hydrate = (c: BillingConfig) => {
    setServerCost(String(c.server_cost_per_min));
    setMinPrice(String(c.min_client_price));
    setMargin(String(c.profit_margin_percent));
    setAssistMin(String(c.assistant_min_per_min ?? c.min_client_price ?? 1));
    setAnnounceMin(String(c.announcement_min_per_min ?? c.min_client_price ?? 1));
    setAssistMinSecs(String(c.assistant_min_bill_seconds ?? 0));
    setAnnounceMinSecs(String(c.announcement_min_bill_seconds ?? 0));
    setTopups((c.wallet_topup_amounts || []).join(", "));
  };

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getBilling()
      .then((c) => { setCfg(c); hydrate(c); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const cost = toNum(serverCost);
  const marginPct = toNum(margin);
  const floor = toNum(minPrice);
  const aMin = toNum(assistMin);
  const nMin = toNum(announceMin);
  const aMinSecs = Math.max(0, Math.floor(toNum(assistMinSecs)));
  const nMinSecs = Math.max(0, Math.floor(toNum(announceMinSecs)));
  const neverLoss = Math.max(cost * (1 + marginPct / 100), floor);

  const save = () => {
    const amounts = topups.split(",").map((s) => toNum(s.trim())).filter((n) => n > 0);
    run(async () => {
      const out = await updateBilling({
        server_cost_per_min: cost,
        min_client_price: floor,
        profit_margin_percent: marginPct,
        assistant_min_per_min: aMin,
        announcement_min_per_min: nMin,
        assistant_min_bill_seconds: aMinSecs,
        announcement_min_bill_seconds: nMinSecs,
        wallet_topup_amounts: amounts,
      });
      setCfg(out);
    }, "Billing config saved ✓ (applied dynamically)");
  };

  const valid = cost >= 0 && floor >= 0 && marginPct >= 0 && aMin >= 0 && nMin >= 0
    && aMinSecs >= 0 && nMinSecs >= 0 && amountsValid(topups);

  return (
    <>
      <PageHeader title="Billing config" subtitle="Per-minute pricing formula — monthly plans are on the Plans page">
        <button className="btn-secondary text-xs" onClick={load} disabled={loading}>↻ Reset</button>
        <button className="btn text-xs" disabled={busy || !valid || !cfg} onClick={save}>
          {busy ? "Saving…" : "💾 Save changes"}
        </button>
      </PageHeader>

      {(msg || err) && (
        <div className={`mb-4 p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
          {msg || err}
        </div>
      )}

      <StateBox loading={loading} error={error}>
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="space-y-4">
          <div className="card p-5 space-y-4">
            <h2 className="text-sm font-bold">Customer ₹/min — rate card</h2>
            <p className="text-xs text-gray-500 leading-relaxed">
              What a customer pays per minute = <b className="text-gray-300">their agent&apos;s model
              prices</b> (set per model on the Models page) <b className="text-gray-300">+ server cost</b> below —
              <b className="text-gray-300"> assistant</b> uses LLM + STT + TTS,{" "}
              <b className="text-gray-300">announcement</b> uses TTS only (fixed script). The per-mode
              minimums are the floor of that rate; below that the mode minimum applies instead. Try any
              combination in the <span className="text-gray-300">Pricing calculator</span> below.
            </p>
            <Field label="Server cost ₹ / min (infra: telephony + compute)" hint="Added to every call's rate. Not shown separately to users.">
              <input className="input" type="number" step="0.01" min="0" value={serverCost} onChange={(e) => setServerCost(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Assistant minimum ₹ / min" hint="Assistant-mode calls never bill below this rate.">
                <input className="input" type="number" step="0.01" min="0" value={assistMin} onChange={(e) => setAssistMin(e.target.value)} />
              </Field>
              <Field label="Announcement minimum ₹ / min" hint="Announcement-mode calls never bill below this rate.">
                <input className="input" type="number" step="0.01" min="0" value={announceMin} onChange={(e) => setAnnounceMin(e.target.value)} />
              </Field>
            </div>
          </div>

          <div className="card p-5 space-y-4">
            <h2 className="text-sm font-bold">Minimum billed duration (seconds)</h2>
            <p className="text-xs text-gray-500 leading-relaxed">
              Enterprise billing: a call shorter than the minimum still bills the full minimum
              (e.g. <b className="text-gray-300">30</b> → a 9s call bills as 30s at the applied rate).
              Infra costs always use the <b className="text-gray-300">actual</b> duration — only the
              customer charge is floored. <b className="text-gray-300">0 = bill actual duration.</b>{" "}
              Bills compose as <b className="text-gray-300">TTS + Telephony + Server</b> for announcements
              and <b className="text-gray-300">STT + LLM + TTS + Telephony + Server</b> for assistants.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Assistant minimum seconds" hint="0 = off. Short assistant calls bill this many seconds.">
                <input className="input" type="number" step="1" min="0" value={assistMinSecs} onChange={(e) => setAssistMinSecs(e.target.value)} />
              </Field>
              <Field label="Announcement minimum seconds" hint="0 = off. Short announcement calls bill this many seconds.">
                <input className="input" type="number" step="1" min="0" value={announceMinSecs} onChange={(e) => setAnnounceMinSecs(e.target.value)} />
              </Field>
            </div>
          </div>
          </div>

          <div className="space-y-4">
            <div className="card p-5 space-y-4">
              <h2 className="text-sm font-bold">Safety floor (never a loss)</h2>
              <Field label="Guaranteed margin %" hint="Per-call floor = your real cost × (1 + margin).">
                <input className="input" type="number" step="1" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
              </Field>
              <Field label="Absolute minimum ₹ / call" hint="Second floor — a call never bills less than this.">
                <input className="input" type="number" step="0.01" min="0" value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
              </Field>
              <div className="rounded-xl bg-gray-800/50 border border-gray-800 p-3 text-xs text-gray-400">
                <span className="font-semibold text-gray-300">Floor preview:</span> worst case, a 1-minute
                call bills <span className="font-bold text-emerald-300">{fmtINR(neverLoss)}</span> even if
                the rate card prices lower — rate-card prices above this are charged as-is.
              </div>
            </div>

            <div className="card p-5 space-y-4">
              <h2 className="text-sm font-bold">Wallet top-ups</h2>
              <Field label="Suggested amounts (₹, comma-separated)" hint="Customers may also enter any custom amount.">
                <input className="input" value={topups} onChange={(e) => setTopups(e.target.value)} placeholder="100, 250, 500, 1000" />
              </Field>
              <div className="flex flex-wrap gap-1.5">
                {topups.split(",").map((s) => toNum(s.trim())).filter((n) => n > 0).map((n, i) => (
                  <span key={i} className="pill pill-green">{fmtINR(n)}</span>
                ))}
              </div>
            </div>
          </div>
        </div>
        <RateCalculator />
      </StateBox>
    </>
  );
}

function amountsValid(topups: string): boolean {
  const parts = topups.split(",").map((s) => s.trim()).filter(Boolean);
  return parts.length > 0 && parts.every((p) => Number(p) > 0);
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 font-medium">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="text-[10px] text-gray-600 mt-1 block">{hint}</span>}
    </label>
  );
}
