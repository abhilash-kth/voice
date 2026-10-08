"use client";

// Wallet tab orchestrator — visuals live in ./billing/* (≤300-line rule):
//   billing/WalletStatCards.tsx  balance hero + usage stat cards
//   billing/TopUpCard.tsx        subscription purchase + top-ups (presets + custom)
//   billing/BillingTables.tsx    transaction ledger + per-call billing table
//   billing/types.ts             shared Tx type + date formatting
import { useCallback, useEffect, useState } from "react";
import { getUsage, getWallet, Usage } from "@/lib/api";
import WalletStatCards from "./billing/WalletStatCards";
import TopUpCard from "./billing/TopUpCard";
import BillingTables from "./billing/BillingTables";
import type { Tx } from "./billing/types";

export default function BillingPanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Tx[]>([]);
  const [amounts] = useState<number[]>([100, 250, 500, 1000]);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [u, w] = await Promise.all([getUsage(), getWallet()]);
      setUsage(u);
      setBalance(w.balance);
      setTransactions((w.transactions as Tx[]) || []);
      setLoading(false);
    } catch (e) {
      setMsg((e as Error).message);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

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

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <WalletStatCards usage={usage} balance={balance} transactions={transactions} />
      <TopUpCard amounts={amounts} onChanged={load} />
      <BillingTables usage={usage} balance={balance} transactions={transactions} />
    </div>
  );
}
