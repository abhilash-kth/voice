"use client";

import { useEffect, useState } from "react";
import { getUsage, getWallet, recharge, Usage } from "@/lib/api";

export default function BillingPanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<{ ts: string; kind: string; amount: number }[]>([]);
  const [amounts, setAmounts] = useState<number[]>([100, 250, 500, 1000]);
  const [msg, setMsg] = useState("");

  const load = async () => {
    try {
      const [u, w] = await Promise.all([getUsage(), getWallet()]);
      setUsage(u);
      setBalance(w.balance);
      setTransactions((w.transactions as any) || []);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const addFunds = async (amt: number) => {
    await recharge(amt);
    setMsg(`Recharged ₹${amt} ✅`);
    load();
  };

  if (!usage || balance === null) {
    return <div className="text-gray-400">Loading billing data... {msg && <span className="text-red-400">{msg}</span>}</div>;
  }

  const cards = [
    { label: "Wallet Balance", value: `₹${balance}`, color: "text-green-400" },
    { label: "Total Calls", value: usage.totalCallsCount, color: "text-white" },
    { label: "Minutes Used", value: `${usage.totalMinutesUsed} min`, color: "text-blue-400" },
    { label: "Customer Spend", value: `₹${usage.currentMonthSpend}`, color: "text-yellow-400" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {cards.map((c) => (
          <div key={c.label} className="bg-gray-800/80 p-4 rounded-xl border border-gray-700">
            <p className="text-gray-400 text-xs uppercase font-semibold">{c.label}</p>
            <p className={`text-3xl font-extrabold mt-1 ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Recharge */}
      <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800">
        <h3 className="text-sm font-bold text-gray-400 uppercase mb-3">Add Balance</h3>
        <div className="flex flex-wrap gap-2">
          {amounts.map((a) => (
            <button
              key={a}
              onClick={() => addFunds(a)}
              className="bg-gray-800 hover:bg-blue-600 border border-gray-700 rounded-lg px-4 py-2 text-sm font-semibold"
            >
              + ₹{a}
            </button>
          ))}
        </div>
        {msg && <p className="text-green-400 text-sm mt-3">{msg}</p>}
      </div>

      {/* Recent transactions */}
      {transactions.length > 0 && (
        <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800">
          <h3 className="text-sm font-bold text-gray-400 uppercase mb-3">Transactions</h3>
          <div className="space-y-2">
            {transactions.slice(0, 8).map((t, i) => (
              <div key={i} className="flex justify-between text-sm">
                <span className="text-gray-400">{t.ts} · {t.kind}</span>
                <span className={t.amount >= 0 ? "text-green-400" : "text-red-400"}>
                  {t.amount >= 0 ? "+" : ""}₹{t.amount}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent calls (from usage) */}
      <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800 overflow-x-auto">
        <h3 className="text-sm font-bold text-gray-400 uppercase mb-3">Recent Calls</h3>
        <table className="w-full text-left text-sm text-gray-300">
          <thead className="bg-gray-800 text-gray-400 uppercase text-xs">
            <tr>
              <th className="p-3">Call</th>
              <th className="p-3">Mode</th>
              <th className="p-3">Duration</th>
              <th className="p-3">TTS</th>
              <th className="p-3">LLM Tokens</th>
              <th className="p-3">Billed</th>
              <th className="p-3">Provider Cost</th>
              <th className="p-3">Cost/min</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {usage.recentCalls.length === 0 && (
              <tr><td colSpan={8} className="p-3 text-gray-500">No completed calls yet.</td></tr>
            )}
            {usage.recentCalls.map((c: any) => (
              <tr key={c.id} className="hover:bg-gray-800/50">
                <td className="p-3 font-mono text-blue-400">{c.id}</td>
                <td className="p-3">{c.mode}</td>
                <td className="p-3">{c.durationSeconds}s</td>
                <td className="p-3">{c.ttsChars} chars</td>
                <td className="p-3">{c.tokensUsed} tokens</td>
                <td className="p-3 font-bold text-green-400">{c.costToUser}</td>
                <td className="p-3 text-red-400">₹{c.providerCost}</td>
                <td className="p-3 text-yellow-300">₹{c.costPerMin}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
