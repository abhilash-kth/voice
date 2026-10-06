"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import { ModePricingCard, type ModePricingState } from "@/components/ModePricingCard";
import { getBilling, updateBilling, type BillingConfig } from "@/lib/billing";
import { fmtINR, toNum } from "@/lib/format";

export default function BillingPage() {
  const [cfg, setCfg] = useState<BillingConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const [serverCost, setServerCost] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [margin, setMargin] = useState("");
  const [topups, setTopups] = useState("");
  const [modePricing, setModePricing] = useState<ModePricingState>({
    announcement: "0", assistant: "0", misc: "0", tiers: [],
  });

  const hydrate = (c: BillingConfig) => {
    setServerCost(String(c.server_cost_per_min));
    setMinPrice(String(c.min_client_price));
    setMargin(String(c.profit_margin_percent));
    setTopups((c.wallet_topup_amounts || []).join(", "));
    setModePricing({
      announcement: String(c.announcement_price_per_min ?? 0),
      assistant: String(c.assistant_price_per_min ?? 0),
      misc: String(c.misc_fee_per_min ?? 0),
      tiers: (c.concurrency_addons || []).map((t) => ({
        up_to: String(t.up_to), addon: String(t.addon_per_min),
      })),
    });
  };

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getBilling()
      .then((c) => {
        setCfg(c);
        hydrate(c);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // Never-loss safety floor preview: even if a call's rate card prices low,
  // the customer pays at least this per minute.
  const cost = toNum(serverCost);
  const marginPct = toNum(margin);
  const withMargin = cost * (1 + marginPct / 100);
  const floor = toNum(minPrice);
  const effective = Math.max(withMargin, floor);

  const save = () => {
    const amounts = topups
      .split(",")
      .map((s) => toNum(s.trim()))
      .filter((n) => n > 0);
    const patch: Partial<BillingConfig> = {
      server_cost_per_min: cost,
      min_client_price: floor,
      profit_margin_percent: marginPct,
      wallet_topup_amounts: amounts,
      announcement_price_per_min: toNum(modePricing.announcement),
      assistant_price_per_min: toNum(modePricing.assistant),
      misc_fee_per_min: toNum(modePricing.misc),
      concurrency_addons: modePricing.tiers
        .map((t) => ({ up_to: Math.trunc(toNum(t.up_to)), addon_per_min: toNum(t.addon) }))
        .filter((t) => t.up_to > 0),
    };
    run(async () => {
      const out = await updateBilling(patch);
      setCfg(out);
    }, "Billing config saved ✓ (customers see it after a config reload)");
  };

  const valid = cost >= 0 && floor >= 0 && marginPct >= 0;

  return (
    <>
      <PageHeader title="Billing config" subtitle="Platform pricing formula — applied dynamically, no redeploy needed">
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
          <div className="card p-5 space-y-4">
            <h2 className="text-sm font-bold">Safety floor (never a loss)</h2>
            <p className="text-xs text-gray-500 leading-relaxed">
              Customer ₹/min normally comes from the <b className="text-gray-300">rate card</b> — the
              per-model prices you set on the Models page (LLM + STT + TTS of the agent), or the flat
              per-mode price on the right — plus the concurrency surcharge and misc fee. If that total is
              ever <b className="text-gray-300">below your real cost</b>, the customer is automatically
              billed the floor instead. You never lose money on a call.
            </p>

            <Field label="Your cost ₹ / min (infra: telephony + compute)" hint="Server-side cost baseline. Not shown to users.">
              <input className="input" type="number" step="0.01" min="0" value={serverCost} onChange={(e) => setServerCost(e.target.value)} />
            </Field>

            <Field label="Guaranteed margin %" hint="Floor = your cost × (1 + margin). Customers never pay less than this markup on real cost.">
              <input className="input" type="number" step="1" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
            </Field>

            <Field label="Absolute minimum ₹ / min" hint="Second floor — customers never pay less than this per minute, whatever the math says.">
              <input className="input" type="number" step="0.01" min="0" value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
            </Field>

            <div className="rounded-xl bg-gray-800/50 border border-gray-800 p-3 text-xs text-gray-400">
              <span className="font-semibold text-gray-300">Floor preview:</span> worst case, customers pay{" "}
              <span className="font-bold text-emerald-300">{fmtINR(effective)}/min</span>
              {floor > withMargin ? " (absolute minimum)" : " (cost + guaranteed margin)"} — rate-card
              prices above this are charged as-is.
            </div>
          </div>

          <div className="space-y-4">
            <ModePricingCard value={modePricing} onChange={setModePricing} />

            <div className="card p-5 space-y-4">
              <h2 className="text-sm font-bold">Wallet top-ups</h2>
              <Field label="Amounts offered in the dashboard (₹, comma-separated)" hint="Customers pick one of these when recharging.">
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
      </StateBox>
    </>
  );
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
