"use client";
import { useState } from "react";
import { recharge } from "@/lib/api";
import SubscriptionPanel from "@/components/SubscriptionPanel";

/** "Add Balance": subscription purchase panel + quick preset top-ups + custom amount. */
export default function TopUpCard({ amounts, onChanged }: {
  amounts: number[];
  onChanged: () => void;
}) {
  const [msg, setMsg] = useState("");
  const [recharging, setRecharging] = useState<number | null>(null);
  const [customAmt, setCustomAmt] = useState("");

  const addFunds = async (amt: number) => {
    setRecharging(amt);
    try {
      await recharge(amt);
      setMsg(`Recharged ₹${amt} successfully ✅`);
      onChanged();
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setRecharging(null);
    }
  };

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-5 sm:p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
        <div>
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <span className="w-6 h-6 rounded-lg bg-blue-600 flex items-center justify-center text-xs">+</span>
            Add Balance
          </h3>
          <p className="text-xs text-gray-500 mt-1">Top-up instantly • UPI / Card • Balance updates in real-time</p>
        </div>
        <div className="text-xs text-gray-400 bg-gray-800 rounded-full px-3 py-1.5 border border-gray-700">
          💡 Calls & monthly plan auto-deduct from the wallet
        </div>
      </div>

      <SubscriptionPanel onChanged={onChanged} />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {amounts.map((a) => (
          <button
            key={a}
            onClick={() => addFunds(a)}
            disabled={recharging !== null}
            className="group relative overflow-hidden rounded-xl bg-gray-800 hover:bg-blue-600 border border-gray-700 hover:border-blue-500 p-4 text-left transition-all hover:shadow-lg hover:shadow-blue-600/20 hover:-translate-y-0.5 disabled:opacity-50"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-bold text-white group-hover:text-white">+ ₹{a}</span>
              <span className="text-gray-500 group-hover:text-blue-200 text-xs">→</span>
            </div>
            <p className="text-[11px] text-gray-500 group-hover:text-blue-100 mt-1">
              {a >= 500 ? "Popular" : a >= 250 ? "Standard" : "Quick top-up"}
            </p>
            {recharging === a && (
              <div className="absolute inset-0 bg-blue-600/90 flex items-center justify-center text-xs font-bold text-white">
                Processing...
              </div>
            )}
          </button>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <input
          type="number"
          min={1}
          value={customAmt}
          onChange={(e) => setCustomAmt(e.target.value)}
          placeholder="Custom amount ₹"
          className="flex-1 max-w-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
        />
        <button
          onClick={() => {
            const amt = Math.floor(Number(customAmt));
            if (amt > 0) { addFunds(amt); setCustomAmt(""); }
          }}
          disabled={recharging !== null || Math.floor(Number(customAmt)) <= 0}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
        >
          {recharging !== null ? "Processing…" : "Add custom amount"}
        </button>
      </div>

      {msg && (
        <div className={`mt-4 rounded-xl px-4 py-3 text-sm border ${msg.includes("Recharged") ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-amber-500/10 border-amber-500/20 text-amber-300"}`}>
          {msg}
        </div>
      )}
    </div>
  );
}
