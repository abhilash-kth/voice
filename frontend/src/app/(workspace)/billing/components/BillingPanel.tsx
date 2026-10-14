"use client";

import { useQuery } from "@tanstack/react-query";
import { getUsage, getWallet, Usage } from "@/lib/index";
import { LoadingGrid } from "../../../../components/LoadingGrid";
import WalletStats from "@/app/(workspace)/billing/components/WalletStats";
import AddBalance from "@/app/(workspace)/billing/components/AddBalance";
import MyPlan from "@/app/(workspace)/billing/components/MyPlan";
import SubscriptionPanel from "./SubscriptionPanel";
import RecentTransactions from "./RecentTransactions";
import { WalletCards } from "lucide-react";

interface Tx {
  ts: string;
  kind: string;
  amount: number;
  note?: string;
}

export default function BillingPanel() {
  const { data, error, isPending } = useQuery({
    queryKey: ["usage", "wallet-balance"],
    queryFn: async () => {
      const [u, w] = await Promise.all([getUsage(), getWallet()]);
      return {
        usage: u,
        balance: w.balance,
        transactions: w.transactions,
      };
    },
  });

  if (error) {
    return (
      <div className="rounded-2xl border border-destructive/20 bg-destructive/10 p-6 text-sm font-medium text-destructive">
        Failed to load billing data:{" "}
        {error instanceof Error ? error.message : "Network error"}
      </div>
    );
  }

  // Safe nullish fallbacks to prevent background refetch unmounts
  const usage: Usage | undefined = data?.usage as Usage | undefined;
  const balance: number = data?.balance ?? 0;
  const transactions: Tx[] = (data?.transactions as Tx[]) ?? [];
  const recentCalls = usage?.recentCalls ?? [];

  const avgCost =
    usage && usage.totalCallsCount > 0
      ? (usage.currentMonthSpend / usage.totalCallsCount).toFixed(2)
      : "0";

  const spendTx = transactions.filter((t) => t.kind === "spend");
  const rechargeTx = transactions.filter((t) => t.kind === "recharge");
  const totalRecharged = rechargeTx.reduce((s, t) => s + t.amount, 0);
  const totalSpent = Math.abs(spendTx.reduce((s, t) => s + t.amount, 0));

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
    <div className="mx-auto space-y-6">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <WalletCards className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
            Billing
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Manage your wallet, usage, subscription, and transactions.
          </p>
        </div>
      </div>

      {/* Header Stats */}
      <WalletStats />

      {/* Add Balance */}
      <AddBalance />

      {/* My Current Plan */}
      <MyPlan />

      {/* subcription card */}
      <SubscriptionPanel />

      {/* recent transactions */}
      <RecentTransactions transactions={transactions} />

      {/* Tables Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Calls */}
        {/* <div className="overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6 lg:col-span-2">
          <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
              Recent Calls • Billing Details
            </h3>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 font-semibold text-blue-600 dark:text-blue-400">
                {recentCalls.length} calls
              </span>
              <span className="rounded-full border border-border bg-muted/40 px-2.5 py-1 font-medium text-muted-foreground">
                Auto-deducts
              </span>
            </div>
          </div>

    
          <div className="hidden overflow-x-auto rounded-xl border border-border bg-background sm:block">
            <table className="w-full text-left">
              <thead className="border-b border-border bg-muted/40 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="p-3.5">Call</th>
                  <th className="p-3.5">Mode</th>
                  <th className="p-3.5">Duration</th>
                  <th className="p-3.5">Usage</th>
                  <th className="p-3.5">Billed</th>
                  <th className="p-3.5">Provider Cost</th>
                  <th className="p-3.5">Balance After</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border text-sm">
                {recentCalls.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center">
                      <div className="flex flex-col items-center">
                        <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-lg">
                          📞
                        </div>
                        <p className="text-sm font-medium text-foreground">
                          No completed calls yet
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Make a call to see billing deduction
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
                {recentCalls.map((c: any, idx: number) => {
                  const billed = Number(c.costToUserNumber || 0);
                  return (
                    <tr
                      key={c.id || idx}
                      className="transition-colors hover:bg-muted/30"
                    >
                      <td className="p-3.5">
                        <div className="flex items-center gap-2">
                          <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 font-mono text-[11px] font-bold text-blue-600 dark:text-blue-400">
                            {idx + 1}
                          </div>
                          <div>
                            <p className="max-w-[90px] truncate font-mono text-xs font-semibold text-primary">
                              {String(c.id).slice(0, 8)}
                            </p>
                            <p className="text-[10px] text-muted-foreground">
                              {c.date?.slice(0, 16) || ""}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center rounded-full border border-border bg-muted/40 px-2 py-1 text-[11px] font-medium text-muted-foreground capitalize">
                          {c.mode}
                        </span>
                      </td>
                      <td className="p-3.5">
                        <span className="font-semibold tabular-nums text-foreground">
                          {c.durationSeconds}s
                        </span>
                        <p className="text-[11px] text-muted-foreground">
                          {c.costPerMin ? `₹${c.costPerMin}/min` : ""}
                        </p>
                      </td>
                      <td className="p-3.5">
                        <p className="text-xs font-medium text-foreground">
                          {c.ttsChars} chars
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          {c.tokensUsed} tokens
                        </p>
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-bold text-emerald-700 dark:text-emerald-400">
                          ₹{billed.toFixed(2)}
                        </span>
                      </td>
                      <td className="p-3.5">
                        <span className="text-xs font-medium tabular-nums text-rose-600 dark:text-rose-400">
                          ₹{Number(c.providerCost || 0).toFixed(2)}
                        </span>
                      </td>
                      <td className="p-3.5">
                        <div className="text-xs">
                          <p className="text-muted-foreground">After call</p>
                          <p className="font-bold tabular-nums text-foreground">
                            ₹
                            {(
                              balance +
                              totalSpent -
                              recentCalls
                                .slice(0, idx)
                                .reduce(
                                  (s: number, x: any) =>
                                    s + Number(x.costToUserNumber || 0),
                                  0,
                                )
                            ).toFixed(2)}
                          </p>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

         
          <div className="space-y-3 sm:hidden">
            {recentCalls.length === 0 && (
              <div className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center">
                <p className="text-sm text-muted-foreground">No calls yet</p>
              </div>
            )}
            {recentCalls.map((c: any, idx: number) => (
              <div
                key={c.id || idx}
                className="rounded-xl border border-border bg-muted/20 p-4"
              >
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 text-xs font-bold text-blue-600 dark:text-blue-400">
                      {idx + 1}
                    </div>
                    <div>
                      <p className="font-mono text-xs font-bold text-primary">
                        {String(c.id).slice(0, 12)}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        {c.mode} • {c.durationSeconds}s
                      </p>
                    </div>
                  </div>
                  <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-bold text-emerald-700 dark:text-emerald-400">
                    ₹{Number(c.costToUserNumber || 0).toFixed(2)}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-border/60 bg-background p-2.5">
                    <p className="text-[11px] text-muted-foreground">Usage</p>
                    <p className="font-medium text-foreground">
                      {c.ttsChars} chars • {c.tokensUsed} tokens
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background p-2.5">
                    <p className="text-[11px] text-muted-foreground">
                      Provider Cost
                    </p>
                    <p className="font-medium text-rose-600 dark:text-rose-400">
                      ₹{Number(c.providerCost || 0).toFixed(2)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div> */}
      </div>
    </div>
  );
}
