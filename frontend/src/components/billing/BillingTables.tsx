"use client";
import { Usage } from "@/lib/api";
import { formatTxDate, type Tx } from "./types";

/** Bottom half of the Wallet tab: transaction ledger + per-call billing table. */
export default function BillingTables({
  usage, balance, transactions,
}: { usage: Usage; balance: number; transactions: Tx[] }) {
  const spendTx = transactions.filter((t) => t.kind === "spend");
  const totalSpent = Math.abs(spendTx.reduce((s, t) => s + t.amount, 0));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Transaction ledger */}
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
                    <p className="text-[11px] text-gray-500 truncate mt-0.5">{formatTxDate(t.ts)} {t.note ? `• ${t.note}` : ""}</p>
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
              <span className="font-semibold text-gray-300">How billing works:</span> every completed call
              automatically deducts its billed amount (model rate card + server) from your wallet, and your
              monthly plan renews from it too. If balance hits ₹0, new calls are blocked until recharge.
            </p>
          </div>
        </div>
      </div>

      {/* Per-call billing table */}
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
  );
}
