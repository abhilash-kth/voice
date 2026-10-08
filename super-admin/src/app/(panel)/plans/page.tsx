"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import {
  createPlan, deletePlan, getBilling, listPlans, listSubscriptions,
  updateBilling, updatePlan, type PlanTier, type SubscriptionRow,
} from "@/lib/billing";
import { fmtINR, toNum } from "@/lib/format";

/**
 * Monthly subscription pricing: agent-capacity plans (platform fee per agent
 * count), price per extra concurrency line, telephony rent, and KB packs —
 * plus a read-only list of subscribers. Per-minute pricing is on Billing.
 */
export default function PlansPage() {
  const [plans, setPlans] = useState<PlanTier[]>([]);
  const [subs, setSubs] = useState<SubscriptionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const [kind, setKind] = useState<"capacity" | "kb_pack">("capacity");
  const [label, setLabel] = useState("");
  const [units, setUnits] = useState("");
  const [faqs, setFaqs] = useState("");
  const [price, setPrice] = useState("");
  const [linePrice, setLinePrice] = useState("");
  const [teleRent, setTeleRent] = useState("");
  const [edits, setEdits] = useState<Record<string, PlanTier>>({});

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([listPlans(), listSubscriptions(), getBilling()])
      .then(([p, s, b]) => {
        setPlans(p.items);
        setSubs(s.items);
        setLinePrice(String(b.concurrency_line_price_per_month ?? 0));
        setTeleRent(String(b.telephony_rent_per_month ?? 0));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const edited = (p: PlanTier) => edits[p.id] || p;
  const setEdit = (p: PlanTier, patch: Partial<PlanTier>) =>
    setEdits((e) => ({ ...e, [p.id]: { ...edited(p), ...patch } }));

  const add = () =>
    run(async () => {
      await createPlan({
        kind, label: label.trim(), units: Math.trunc(toNum(units)),
        faqs: kind === "kb_pack" ? Math.trunc(toNum(faqs)) : 0,
        price_per_month: toNum(price), enabled: true,
        sort_order: plans.length,
      });
      setLabel(""); setUnits(""); setFaqs(""); setPrice("");
      load();
    }, "Plan added ✓");

  const saveRow = (p: PlanTier) =>
    run(async () => {
      const e = edited(p);
      await updatePlan(p.id, {
        label: e.label, units: e.units, faqs: e.faqs,
        price_per_month: Number(e.price_per_month), enabled: e.enabled,
        sort_order: e.sort_order,
      });
      setEdits((x) => { const n = { ...x }; delete n[p.id]; return n; });
      load();
    }, "Plan saved ✓");

  const saveGlobals = () =>
    run(async () => {
      await updateBilling({
        concurrency_line_price_per_month: toNum(linePrice),
        telephony_rent_per_month: toNum(teleRent),
      });
    }, "Monthly prices saved ✓");

  return (
    <>
      <PageHeader title="Monthly plans" subtitle="What customers subscribe to before building agents">
        <button className="btn-secondary text-xs" onClick={load} disabled={loading}>↻ Refresh</button>
      </PageHeader>

      {(msg || err) && (
        <div className={`mb-4 p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
          {msg || err}
        </div>
      )}

      <StateBox loading={loading} error={error}>
        <div className="grid lg:grid-cols-2 gap-4 mb-4">
          <div className="card p-5 space-y-3">
            <h2 className="text-sm font-bold">Concurrency &amp; telephony (₹ / month)</h2>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Extra concurrent line ₹/mo</span>
                <input className="input mt-1" type="number" min="0" step="1" value={linePrice} onChange={(e) => setLinePrice(e.target.value)} />
                <span className="text-[10px] text-gray-600 mt-1 block">First line is free; each extra line costs this per month.</span>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Telephony rent ₹/mo</span>
                <input className="input mt-1" type="number" min="0" step="1" value={teleRent} onChange={(e) => setTeleRent(e.target.value)} />
                <span className="text-[10px] text-gray-600 mt-1 block">Monthly number/telephony access rent.</span>
              </label>
            </div>
            <button className="btn text-xs" disabled={busy} onClick={saveGlobals}>💾 Save monthly prices</button>
          </div>

          <div className="card p-5 space-y-3">
            <h2 className="text-sm font-bold">Add a plan</h2>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Type</span>
                <select className="input mt-1" value={kind} onChange={(e) => setKind(e.target.value as "capacity" | "kb_pack")}>
                  <option value="capacity">Agent plan (platform fee)</option>
                  <option value="kb_pack">KB pack (extra limits)</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Label</span>
                <input className="input mt-1" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={kind === "capacity" ? "3-agent plan" : "KB +100k"} />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">{kind === "capacity" ? "Agents allowed" : "Extra KB chars"}</span>
                <input className="input mt-1" type="number" min="0" value={units} onChange={(e) => setUnits(e.target.value)} placeholder={kind === "capacity" ? "3" : "100000"} />
              </label>
              {kind === "kb_pack" && (
                <label className="block">
                  <span className="text-xs text-gray-400 font-medium">Extra FAQs</span>
                  <input className="input mt-1" type="number" min="0" value={faqs} onChange={(e) => setFaqs(e.target.value)} placeholder="100" />
                </label>
              )}
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Price ₹ / month</span>
                <input className="input mt-1" type="number" min="0" step="1" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="499" />
              </label>
            </div>
            <button className="btn text-xs" disabled={busy || !label.trim() || toNum(units) <= 0} onClick={add}>＋ Add plan</button>
          </div>
        </div>

        <div className="card p-5 mb-4 overflow-x-auto">
          <h2 className="text-sm font-bold mb-3">Plans on sale</h2>
          <table className="table">
            <thead><tr><th>Type</th><th>Label</th><th className="text-right">Allowance</th><th className="text-right">₹/mo</th><th>Enabled</th><th className="text-right">Actions</th></tr></thead>
            <tbody>
              {plans.map((p) => {
                const e = edited(p);
                return (
                  <tr key={p.id}>
                    <td><span className={`pill ${p.kind === "capacity" ? "pill-blue" : "pill-gray"}`}>{p.kind === "capacity" ? "Agents" : "KB pack"}</span></td>
                    <td><input className="input w-40" value={e.label} onChange={(ev) => setEdit(p, { label: ev.target.value })} /></td>
                    <td className="text-right">
                      <input className="input w-28 text-right" type="number" min="0" value={e.units} onChange={(ev) => setEdit(p, { units: Math.trunc(Number(ev.target.value)) })} />
                      <span className="text-[10px] text-gray-500 ml-1">{p.kind === "capacity" ? "agents" : "chars"}{p.kind === "kb_pack" && e.faqs > 0 ? ` + ${e.faqs} FAQs` : ""}</span>
                    </td>
                    <td className="text-right">
                      <input className="input w-24 text-right" type="number" min="0" value={e.price_per_month} onChange={(ev) => setEdit(p, { price_per_month: Number(ev.target.value) })} />
                    </td>
                    <td>
                      <button className={`pill ${e.enabled ? "pill-green" : "pill-gray"}`} onClick={() => setEdit(p, { enabled: !e.enabled })}>{e.enabled ? "on" : "off"}</button>
                    </td>
                    <td className="text-right space-x-2">
                      <button className="btn-secondary text-xs" disabled={busy} onClick={() => saveRow(p)}>Save</button>
                      <button className="btn-danger text-xs" disabled={busy} onClick={() => run(async () => { await deletePlan(p.id); load(); }, "Plan deleted ✓")}>Delete</button>
                    </td>
                  </tr>
                );
              })}
              {plans.length === 0 && <tr><td colSpan={6} className="text-gray-500 text-xs py-4">No plans yet — add agent-capacity plans (e.g. 3-agent ₹X/mo, 5-agent ₹Y/mo) above.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card p-5 overflow-x-auto">
          <h2 className="text-sm font-bold mb-3">Subscribers</h2>
          <table className="table">
            <thead><tr><th>Customer</th><th>Status</th><th className="text-right">Agents</th><th className="text-right">Lines</th><th>Telephony</th><th className="text-right">₹/mo</th><th>Renews</th></tr></thead>
            <tbody>
              {subs.map((s) => (
                <tr key={s.user_id}>
                  <td>
                    <div className="text-gray-200 text-sm">{s.user_name || s.user_email || s.user_id.slice(0, 10)}{s.user_name && s.user_email ? ` (${s.user_email})` : ""}</div>
                  </td>
                  <td><span className={`pill ${s.status === "active" ? "pill-green" : s.status === "past_due" ? "pill-blue" : "pill-gray"}`}>{s.status}</span></td>
                  <td className="text-right text-xs text-gray-300">{s.agent_limit}</td>
                  <td className="text-right text-xs text-gray-300">{s.concurrency_lines}</td>
                  <td className="text-xs text-gray-300">{s.telephony_rented ? "rented" : "—"}</td>
                  <td className="text-right font-semibold text-emerald-300">{fmtINR(s.monthly_total)}</td>
                  <td className="text-xs text-gray-400">{s.renews_at ? s.renews_at.slice(0, 10) : "—"}</td>
                </tr>
              ))}
              {subs.length === 0 && <tr><td colSpan={7} className="text-gray-500 text-xs py-4">No subscribers yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </StateBox>
    </>
  );
}
