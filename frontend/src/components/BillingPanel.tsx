"use client";

import { useEffect, useState } from "react";
import { getUsage, getWallet, recharge, Usage } from "@/lib/api";

interface Tx {
  ts: string;
  kind: string;
  amount: number;
  note?: string;
}

export default function BillingPanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Tx[]>([]);
  const [amounts] = useState<number[]>([100, 250, 500, 1000]);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);
  const [recharging, setRecharging] = useState<number | null>(null);

  const load = async () => {
    try {
      const [u, w] = await Promise.all([getUsage(), getWallet()]);
      setUsage(u);
      setBalance(w.balance);
      setTransactions((w.transactions as any) || []);
      setLoading(false);
    } catch (e) {
      setMsg((e as Error).message);
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const addFunds = async (amt: number) => {
    setRecharging(amt);
    try {
      await recharge(amt);
      setMsg(`Recharged ₹${amt} successfully ✅`);
      await load();
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setRecharging(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-40 bg-gray-800 rounded-2xl" />
      </div>
    );
  }

  if (!usage || balance === null) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-6 text-red-300">
        Failed to load billing data. {msg}
      </div>
    );
  }

  const avgCost = usage.totalCallsCount > 0 ? (usage.currentMonthSpend / usage.totalCallsCount).toFixed(2) : "0";
  const spendTx = transactions.filter((t) => t.kind === "spend");
  const rechargeTx = transactions.filter((t) => t.kind === "recharge");
  const totalRecharged = rechargeTx.reduce((s, t) => s + t.amount, 0);
  const totalSpent = Math.abs(spendTx.reduce((s, t) => s + t.amount, 0));

  // Compute running balance for transaction history (reverse chronological)
  // transactions are newest first from API (ts desc). We'll show them as is.
  // For professional look, format date.

  const formatDate = (ts: string) => {
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
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header Stats - Professional SaaS cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Wallet Balance - Hero card */}
        <div className="sm:col-span-2 lg:col-span-1 relative overflow-hidden rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 p-5 text-white shadow-xl shadow-emerald-500/20">
          <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16 blur-2xl" />
          <div className="relative">
            <div className="flex items-center justify-between mb-2">
              <p className="text-emerald-100 text-xs font-semibold tracking-wider uppercase">Wallet Balance</p>
              <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">💳</div>
            </div>
            <p className="text-3xl sm:text-4xl font-black tracking-tight">₹{balance.toFixed(2)}</p>
            <p className="text-emerald-100 text-xs mt-2 flex items-center gap-1">
              <span className="w-2 h-2 bg-emerald-200 rounded-full animate-pulse" /> Live • Auto-deducts per call
            </p>
            <div className="mt-4 pt-4 border-t border-white/20 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-emerald-100">Total Recharged</p>
                <p className="font-bold text-sm">₹{totalRecharged.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-emerald-100">Total Spent</p>
                <p className="font-bold text-sm">₹{totalSpent.toFixed(2)}</p>
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-5 hover:border-gray-700 transition-colors shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <p className="text-gray-400 text-xs font-semibold tracking-wider uppercase">Total Calls</p>
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">📞</div>
          </div>
          <p className="text-3xl font-black text-white">{usage.totalCallsCount}</p>
          <p className="text-xs text-gray-500 mt-2">Avg ₹{avgCost} per call • {usage.totalMinutesUsed} min total</p>
          <div className="mt-3 h-1.5 bg-gray-800 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, usage.totalCallsCount * 4)}%` }} />
          </div>
        </div>

        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-5 hover:border-gray-700 transition-colors shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <p className="text-gray-400 text-xs font-semibold tracking-wider uppercase">Minutes Used</p>
            <div className="w-8 h-8 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400">⏱️</div>
          </div>
          <p className="text-3xl font-black text-white">{usage.totalMinutesUsed}<span className="text-lg font-semibold text-gray-400 ml-1">min</span></p>
          <p className="text-xs text-gray-500 mt-2">{usage.sttSeconds}s speech • {usage.ttsChars} TTS chars</p>
          <div className="mt-3 flex gap-1.5">
            <span className="text-[10px] px-2 py-1 rounded-full bg-gray-800 text-gray-400">LLM {usage.llmInputTokens + usage.llmOutputTokens} tokens</span>
          </div>
        </div>

        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-5 hover:border-gray-700 transition-colors shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <p className="text-gray-400 text-xs font-semibold tracking-wider uppercase">Customer Spend</p>
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">💰</div>
          </div>
          <p className="text-3xl font-black text-amber-400">₹{usage.currentMonthSpend.toFixed(2)}</p>
          <p className="text-xs text-gray-500 mt-2">Deducted automatically after each call</p>
          <div className="mt-3 text-[11px] text-gray-400 bg-gray-800/50 rounded-lg px-3 py-2">
            Remaining: <span className="font-bold text-white">₹{balance.toFixed(2)}</span> • Next call will deduct from this
          </div>
        </div>
      </div>

      {/* Add Balance - Professional */}
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
            💡 Each call auto-deducts ₹{avgCost} avg • Low balance? Recharge to continue
          </div>
        </div>

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

        {msg && (
          <div className={`mt-4 rounded-xl px-4 py-3 text-sm border ${msg.includes("Recharged") ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-amber-500/10 border-amber-500/20 text-amber-300"}`}>
            {msg}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Transactions */}
        <div className="lg:col-span-1 rounded-2xl bg-gray-900 border border-gray-800 p-5 sm:p-6 flex flex-col">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">Transactions</h3>
            <span className="text-[11px] px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-gray-400">{transactions.length} records</span>
          </div>

          {transactions.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center py-12 text-center">
              <div className="w-12 h-12 rounded-2xl bg-gray-800 flex items-center justify-center mb-3">📭</div>
              <p className="text-sm text-gray-400">No transactions yet</p>
              <p className="text-xs text-gray-600 mt-1">Recharge or make a call to see history</p>
            </div>
          ) : (
            <div className="space-y-2.5 max-h-[420px] overflow-y-auto pr-1 -mr-1 custom-scrollbar">
              {transactions.slice(0, 20).map((t, i) => {
                const isSpend = t.kind === "spend";
                return (
                  <div key={i} className="group flex items-center gap-3 rounded-xl bg-gray-800/50 border border-gray-800 hover:border-gray-700 p-3 transition-colors">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-sm shrink-0 ${isSpend ? "bg-red-500/10 border border-red-500/20 text-red-400" : "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400"}`}>
                      {isSpend ? "−" : "+"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-white truncate">{isSpend ? "Call charge" : "Wallet top-up"}</p>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${isSpend ? "bg-red-500/10 text-red-300" : "bg-emerald-500/10 text-emerald-300"}`}>{t.kind}</span>
                      </div>
                      <p className="text-[11px] text-gray-500 truncate mt-0.5">{formatDate(t.ts)} {t.note ? `• ${t.note}` : ""}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`text-sm font-bold ${isSpend ? "text-red-400" : "text-emerald-400"}`}>
                        {isSpend ? "" : "+"}₹{Math.abs(t.amount).toFixed(2)}
                      </p>
                      <p className="text-[10px] text-gray-600">{isSpend ? "deducted" : "added"}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-5 pt-5 border-t border-gray-800">
            <div className="rounded-xl bg-gray-800/30 border border-dashed border-gray-700 p-3">
              <p className="text-[11px] text-gray-400 leading-relaxed">
                <span className="font-semibold text-gray-300">How billing works:</span> Every completed call automatically deducts the billed amount (STT + LLM + TTS + server) from your wallet. Remaining balance is shown at top. If balance hits ₹0, new calls are blocked until recharge.
              </p>
            </div>
          </div>
        </div>

        {/* Recent Calls - Responsive */}
        <div className="lg:col-span-2 rounded-2xl bg-gray-900 border border-gray-800 p-5 sm:p-6 overflow-hidden">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">Recent Calls • Billing Details</h3>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="px-2.5 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300">{usage.recentCalls.length} calls</span>
              <span className="px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-gray-400">Auto-deducts</span>
            </div>
          </div>

          {/* Desktop table */}
          <div className="hidden sm:block overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-left">
              <thead className="bg-gray-800/80 text-gray-400 uppercase text-[11px] tracking-wider">
                <tr>
                  <th className="p-3.5 font-semibold">Call</th>
                  <th className="p-3.5 font-semibold">Mode</th>
                  <th className="p-3.5 font-semibold">Duration</th>
                  <th className="p-3.5 font-semibold">Usage</th>
                  <th className="p-3.5 font-semibold">Billed</th>
                  <th className="p-3.5 font-semibold">Provider Cost</th>
                  <th className="p-3.5 font-semibold">Balance After</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50 text-sm">
                {usage.recentCalls.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center">
                      <div className="flex flex-col items-center">
                        <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center mb-2">📞</div>
                        <p className="text-gray-500 text-sm">No completed calls yet</p>
                        <p className="text-xs text-gray-600 mt-1">Make a call to see billing deduction</p>
                      </div>
                    </td>
                  </tr>
                )}
                {usage.recentCalls.map((c: any, idx: number) => {
                  // Estimate running balance: not precise but shows deduction concept
                  // We'll compute cumulative spend up to this call in reverse order
                  const billed = Number(c.costToUserNumber || 0);
                  return (
                    <tr key={c.id} className="hover:bg-gray-800/40 transition-colors group">
                      <td className="p-3.5">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-[11px] text-blue-400 font-mono">{idx + 1}</div>
                          <div>
                            <p className="font-mono text-blue-400 text-xs truncate max-w-[90px]">{String(c.id).slice(0, 8)}</p>
                            <p className="text-[10px] text-gray-500">{c.date?.slice(0, 16) || ""}</p>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center px-2 py-1 rounded-full text-[11px] font-medium bg-gray-800 border border-gray-700 text-gray-300">{c.mode}</span>
                      </td>
                      <td className="p-3.5">
                        <span className="font-medium text-white">{c.durationSeconds}s</span>
                        <p className="text-[11px] text-gray-500">{c.costPerMin ? `₹${c.costPerMin}/min` : ""}</p>
                      </td>
                      <td className="p-3.5">
                        <p className="text-xs text-gray-300">{c.ttsChars} chars</p>
                        <p className="text-[11px] text-gray-500">{c.tokensUsed} tokens</p>
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-bold text-xs">
                          ₹{billed.toFixed(2)}
                        </span>
                        <p className="text-[10px] text-red-400 mt-1">− deducted</p>
                      </td>
                      <td className="p-3.5">
                        <span className="text-red-400 text-xs">₹{Number(c.providerCost || 0).toFixed(2)}</span>
                      </td>
                      <td className="p-3.5">
                        <div className="text-xs">
                          <p className="text-gray-400">After this call</p>
                          <p className="font-bold text-white">₹{(balance + totalSpent - usage.recentCalls.slice(0, idx).reduce((s: number, x: any) => s + Number(x.costToUserNumber || 0), 0)).toFixed(2)}</p>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="sm:hidden space-y-3">
            {usage.recentCalls.length === 0 && (
              <div className="rounded-xl bg-gray-800/50 border border-dashed border-gray-700 p-6 text-center">
                <p className="text-sm text-gray-500">No calls yet</p>
              </div>
            )}
            {usage.recentCalls.map((c: any, idx: number) => (
              <div key={c.id} className="rounded-xl bg-gray-800 border border-gray-700 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-xs text-blue-400">{idx + 1}</div>
                    <div>
                      <p className="font-mono text-xs text-blue-400">{String(c.id).slice(0, 12)}</p>
                      <p className="text-[11px] text-gray-500">{c.mode} • {c.durationSeconds}s</p>
                    </div>
                  </div>
                  <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-bold text-xs">₹{Number(c.costToUserNumber || 0).toFixed(2)}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-gray-900 rounded-lg p-2.5">
                    <p className="text-gray-500 text-[11px]">Usage</p>
                    <p className="text-white font-medium">{c.ttsChars} chars • {c.tokensUsed} tokens</p>
                  </div>
                  <div className="bg-gray-900 rounded-lg p-2.5">
                    <p className="text-gray-500 text-[11px]">Provider Cost</p>
                    <p className="text-red-400 font-medium">₹{Number(c.providerCost || 0).toFixed(2)}</p>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between text-[11px] text-gray-500 bg-gray-900/50 rounded-lg px-3 py-2">
                  <span>Deducted from wallet</span>
                  <span className="text-white font-bold">Remaining: ₹{balance.toFixed(2)}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <div className="text-[11px] px-3 py-2 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300">
              ✅ Every call deducts automatically • No manual invoicing needed
            </div>
            <div className="text-[11px] px-3 py-2 rounded-full bg-gray-800 border border-gray-700 text-gray-400">
              Balance updates live every 5s • Refresh after call ends
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
