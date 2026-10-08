"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSubscription, purchaseSubscription, type PlanOption, type SubscriptionInfo,
} from "@/lib/api/subs";
import { listAgents } from "@/lib/api";

/**
 * Monthly plan: current entitlements + purchase form (agent-capacity plan,
 * extra concurrency lines, telephony rent, KB packs). Prices come from the
 * Super Admin; the monthly total is computed client-side from the same list.
 */
export default function SubscriptionPanel({ onChanged }: { onChanged?: () => void }) {
  const [info, setInfo] = useState<SubscriptionInfo | null>(null);
  const [agents, setAgents] = useState(0);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const [tierId, setTierId] = useState("");
  const [extraLines, setExtraLines] = useState(0);
  const [telephony, setTelephony] = useState(false);
  const [packIds, setPackIds] = useState<string[]>([]);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([getSubscription(), listAgents()])
      .then(([s, a]) => { setInfo(s); setAgents((a as { agents: unknown[] }).agents?.length || 0); setErr(""); })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  if (loading && !info) return <div className="text-xs text-gray-500 animate-pulse">Loading your plan…</div>;
  if (!info) return <div className="text-xs text-red-300">{err || "Plan info unavailable"}</div>;

  const ent = info.entitlement;
  const linePrice = info.prices.line_price_per_month;
  const teleRent = info.prices.telephony_rent_per_month;
  const chosenTier: PlanOption | undefined = info.plans.capacity.find((t) => t.id === tierId);
  const chosenPacks = info.plans.kb_packs.filter((p) => packIds.includes(p.id));
  const monthly = (chosenTier?.price_per_month || 0)
    + Math.max(extraLines, 0) * linePrice
    + (telephony ? teleRent : 0)
    + chosenPacks.reduce((s, p) => s + p.price_per_month, 0);

  const buy = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      await purchaseSubscription({
        capacity_tier_id: tierId, extra_lines: Math.max(0, Math.trunc(extraLines)),
        telephony, kb_pack_ids: packIds,
      });
      setMsg("Plan activated ✅ — you can build agents and call now.");
      setTierId(""); setExtraLines(0); setTelephony(false); setPackIds([]);
      load();
      onChanged?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const statusPill = ent.status === "active"
    ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
    : ent.status === "past_due"
      ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
      : "bg-gray-800 text-gray-400 border-gray-700";

  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900/60 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-white">Monthly plan</h2>
        <span className={`text-[11px] px-2.5 py-1 rounded-full border ${statusPill}`}>{ent.status}</span>
      </div>

      {ent.status === "active" ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <Stat label="Agents" value={`${agents} / ${ent.agent_limit}`} />
          <Stat label="Concurrent lines" value={String(ent.concurrency_lines)} />
          <Stat label="KB allowance" value={`${(ent.kb_char_limit / 1000).toFixed(0)}k chars · ${ent.kb_faq_limit} FAQs`} />
          <Stat label="Renews" value={ent.renews_at ? ent.renews_at.slice(0, 10) : "—"} sub={`₹${ent.monthly_total.toFixed(2)}/mo`} />
        </div>
      ) : (
        <p className="text-xs text-amber-300/90 bg-amber-500/10 border border-amber-500/30 rounded-xl p-3">
          {ent.status === "past_due"
            ? "Monthly payment due — recharge your wallet to keep calling and building agents."
            : "No active plan. Purchase a monthly plan below to create agents and place calls."}
        </p>
      )}

      <div className="border-t border-gray-800 pt-4 space-y-3">
        <p className="text-xs text-gray-400 font-medium">Change / extend your plan</p>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[11px] text-gray-500">Agent plan (platform fee)</span>
            <select className="input mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                    value={tierId} onChange={(e) => setTierId(e.target.value)}>
              <option value="">— none —</option>
              {info.plans.capacity.map((t) => (
                <option key={t.id} value={t.id}>{t.label} — ₹{t.price_per_month}/mo</option>
              ))}
            </select>
            {info.plans.capacity.length === 0 && (
              <span className="text-[10px] text-gray-600 mt-1 block">Ask the admin to add agent plans (Super Admin → Plans).</span>
            )}
          </label>
          <label className="block">
            <span className="text-[11px] text-gray-500">Extra concurrent lines (+₹{linePrice}/line/mo)</span>
            <input className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                   type="number" min={0} value={extraLines}
                   onChange={(e) => setExtraLines(Number(e.target.value))} />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={telephony} onChange={(e) => setTelephony(e.target.checked)} />
            <span>Telephony rent <span className="text-gray-500">(+₹{teleRent}/mo)</span></span>
          </label>
          {info.plans.kb_packs.map((p) => (
            <label key={p.id} className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={packIds.includes(p.id)}
                     onChange={(e) => setPackIds(e.target.checked ? [...packIds, p.id] : packIds.filter((x) => x !== p.id))} />
              <span>{p.label} <span className="text-gray-500">(+₹{p.price_per_month}/mo)</span></span>
            </label>
          ))}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Total: <b className="text-emerald-300">₹{monthly.toFixed(2)}/month</b></span>
          <button onClick={buy} disabled={busy || monthly <= 0}
                  className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-4 py-2 rounded-lg disabled:opacity-50">
            {busy ? "Activating…" : "Buy & activate (wallet)"}
          </button>
        </div>
        <p className="text-[10px] text-gray-600">
          The first month is charged from your wallet now; renewals run monthly. Recharge below if balance is short.
        </p>
        {err && <p className="text-xs text-red-300">{err}</p>}
        {msg && <p className="text-xs text-emerald-300">{msg}</p>}
      </div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-gray-800/60 border border-gray-800 rounded-xl p-3">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className="text-sm font-bold text-white">{value}</div>
      {sub && <div className="text-[10px] text-emerald-300">{sub}</div>}
    </div>
  );
}
