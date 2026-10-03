"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import { getBilling, updateBilling, type BillingConfig } from "@/lib/api";
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
  const [vsMin, setVsMin] = useState("");
  const [vsMax, setVsMax] = useState("");
  const [vsDefault, setVsDefault] = useState("");

  const hydrate = (c: BillingConfig) => {
    setServerCost(String(c.server_cost_per_min));
    setMinPrice(String(c.min_client_price));
    setMargin(String(c.profit_margin_percent));
    setTopups((c.wallet_topup_amounts || []).join(", "));
    setVsMin(String(c.voice_speed_min));
    setVsMax(String(c.voice_speed_max));
    setVsDefault(String(c.voice_speed_default));
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

  // Live preview: what a customer pays per minute for a model whose provider
  // cost equals serverCost — mirrors app/services/tts_speed + billing logic.
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
      voice_speed_min: toNum(vsMin),
      voice_speed_max: toNum(vsMax),
      voice_speed_default: toNum(vsDefault),
    };
    run(async () => {
      const out = await updateBilling(patch);
      setCfg(out);
    }, "Billing config saved ✓ (customers see it after a config reload)");
  };

  const valid = cost >= 0 && floor >= 0 && marginPct >= 0 &&
    toNum(vsMin) > 0 && toNum(vsMax) >= toNum(vsMin) &&
    toNum(vsDefault) >= toNum(vsMin) && toNum(vsDefault) <= toNum(vsMax);

  return (
    <>
      <PageHeader title="Billing config" subtitle="Platform pricing — applied dynamically, no redeploy needed">
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
            <h2 className="text-sm font-bold">Pricing</h2>

            <Field label="Your cost ₹ / min (infra: telephony + compute)" hint="Server-side cost baseline. Not shown to users.">
              <input className="input" type="number" step="0.01" min="0" value={serverCost} onChange={(e) => setServerCost(e.target.value)} />
            </Field>

            <Field label="Profit margin %" hint="Added on top of your cost to compute customer prices.">
              <input className="input" type="number" step="1" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
            </Field>

            <Field label="Minimum customer price ₹ / min" hint="Floor — customers never pay less than this per minute.">
              <input className="input" type="number" step="0.01" min="0" value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
            </Field>

            <div className="rounded-xl bg-gray-800/50 border border-gray-800 p-3 text-xs text-gray-400">
              <span className="font-semibold text-gray-300">Live preview:</span> a model costing you{" "}
              {fmtINR(cost)}/min bills customers at{" "}
              <span className="font-bold text-emerald-300">{fmtINR(effective)}/min</span>
              {floor > withMargin ? " (floor price applied)" : " (cost + margin)"}.
            </div>
          </div>

          <div className="space-y-4">
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

            <div className="card p-5 space-y-4">
              <h2 className="text-sm font-bold">Voice speed (TTS)</h2>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Min">
                  <input className="input" type="number" step="0.1" min="0.1" value={vsMin} onChange={(e) => setVsMin(e.target.value)} />
                </Field>
                <Field label="Max">
                  <input className="input" type="number" step="0.1" min="0.1" value={vsMax} onChange={(e) => setVsMax(e.target.value)} />
                </Field>
                <Field label="Default">
                  <input className="input" type="number" step="0.1" min="0.1" value={vsDefault} onChange={(e) => setVsDefault(e.target.value)} />
                </Field>
              </div>
              {!valid && vsMin && vsMax && (
                <p className="text-[10px] text-red-300">Speeds must satisfy: 0 &lt; min ≤ default ≤ max.</p>
              )}
              <p className="text-[10px] text-gray-600">Range enforced in the customer agent config; default pre-selects the slider.</p>
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
