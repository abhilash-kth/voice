"use client";
import { Usage } from "@/lib/api";
import type { Tx } from "./types";

/** Top row of the Wallet tab: balance hero + calls/minutes/spend stat cards. */
export default function WalletStatCards({
  usage, balance, transactions,
}: { usage: Usage; balance: number; transactions: Tx[] }) {
  const avgCost = usage.totalCallsCount > 0
    ? (usage.currentMonthSpend / usage.totalCallsCount).toFixed(2) : "0";
  const spendTx = transactions.filter((t) => t.kind === "spend");
  const rechargeTx = transactions.filter((t) => t.kind === "recharge");
  const totalRecharged = rechargeTx.reduce((s, t) => s + t.amount, 0);
  const totalSpent = Math.abs(spendTx.reduce((s, t) => s + t.amount, 0));

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Wallet Balance — hero card */}
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
  );
}
