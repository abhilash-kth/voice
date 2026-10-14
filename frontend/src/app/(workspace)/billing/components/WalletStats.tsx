"use client";

import { useQuery } from "@tanstack/react-query";
import { Wallet, PhoneCall, Clock, IndianRupee, RefreshCw } from "lucide-react";
import { getUsage, getWallet, type Usage } from "@/lib/index";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

type Tx = { ts: string; kind: string; amount: number; note?: string };

const EMPTY_USAGE = {
  totalCallsCount: 0,
  totalMinutesUsed: 0,
  currentMonthSpend: 0,
  sttSeconds: 0,
  ttsChars: 0,
  llmInputTokens: 0,
  llmOutputTokens: 0,
} as Usage;

/**
 * Self-contained wallet header metrics.
 * Cache key shared with BillingPanel: ["usage", "wallet-balance"]
 */
export default function WalletStats() {
  const { data, isPending, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["usage", "wallet-balance"],
    queryFn: async () => {
      const [usage, wallet] = await Promise.all([getUsage(), getWallet()]);
      return {
        usage: usage as Usage,
        balance: Number(wallet.balance ?? 0),
        transactions: (wallet.transactions as Tx[]) ?? [],
      };
    },
  });

  const usage = data?.usage ?? EMPTY_USAGE;
  const balance = data?.balance ?? 0;
  const transactions = data?.transactions ?? [];

  const avgCost =
    usage.totalCallsCount > 0
      ? (usage.currentMonthSpend / usage.totalCallsCount).toFixed(2)
      : "0";

  let totalRecharged = 0;
  let totalSpent = 0;
  for (const t of transactions) {
    if (t.kind === "recharge") totalRecharged += t.amount;
    else if (t.kind === "spend") totalSpent += Math.abs(t.amount);
  }

  return (
    <div className="space-y-3">
      {isError && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
          {error instanceof Error
            ? error.message
            : "Failed to load wallet stats"}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Hero balance */}
        <div className="relative overflow-hidden rounded-2xl bg-primary p-5 text-primary-foreground shadow-sm sm:col-span-2 lg:col-span-1">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.12]"
            style={{
              backgroundImage:
                "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
              backgroundSize: "14px 14px",
            }}
          />
          <div
            className={cn("relative", isPending && "animate-pulse opacity-60")}
          >
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-primary-foreground/70">
                Wallet Balance
              </p>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-foreground/15">
                <Wallet className="h-4 w-4" />
              </div>
            </div>
            <div className="text-3xl font-bold tracking-tight tabular-nums sm:text-4xl">
              {!isPending ? (
                `₹${balance.toFixed(2)}`
              ) : (
                <Skeleton className="h-8 w-30 rounded-full" />
              )}
            </div>
            <p className="mt-2 flex items-center gap-1.5 text-xs text-primary-foreground/75">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-300" />
              </span>
              Live · Auto-deducts per call
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-primary-foreground/20 pt-4 text-xs">
              <div>
                <p className="text-primary-foreground/70">Total Recharged</p>
                <div className="text-sm font-bold tabular-nums">
                  {!isPending ? (
                    `₹${totalRecharged.toFixed(2)}`
                  ) : (
                    <Skeleton className="h-4 w-20 rounded-full opacity-50" />
                  )}
                </div>
              </div>
              <div>
                <p className="text-primary-foreground/70">Total Spent</p>
                <div className="text-sm font-bold tabular-nums">
                  {!isPending ? (
                    `₹${totalSpent.toFixed(2)}`
                  ) : (
                    <Skeleton className="h-4 w-20 rounded-full opacity-50" />
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <StatCard
          pending={isPending}
          label="Total Calls"
          icon={
            <PhoneCall className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          }
          iconWrap="border-blue-500/20 bg-blue-500/10"
          value={String(usage.totalCallsCount)}
          hint={`Avg ₹${avgCost} per call · ${usage.totalMinutesUsed} min total`}
          footer={
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-blue-500"
                style={{
                  width: `${Math.min(100, usage.totalCallsCount * 4)}%`,
                }}
              />
            </div>
          }
        />

        <StatCard
          pending={isPending}
          label="Minutes Used"
          icon={
            <Clock className="h-4 w-4 text-violet-600 dark:text-violet-400" />
          }
          iconWrap="border-violet-500/20 bg-violet-500/10"
          value={
            <>
              {usage.totalMinutesUsed}
              <span className="ml-1 text-lg font-semibold text-muted-foreground">
                min
              </span>
            </>
          }
          hint={`${usage.sttSeconds}s speech · ${usage.ttsChars} TTS chars`}
          footer={
            <div className="mt-3">
              <span className="inline-flex rounded-full border border-border bg-muted/40 px-2 py-1 text-[10px] text-muted-foreground">
                LLM{" "}
                {!isPending ? (
                  usage.llmInputTokens + usage.llmOutputTokens
                ) : (
                  <Skeleton className="h-4 w-8 mx-1 rounded-full" />
                )}{" "}
                tokens
              </span>
            </div>
          }
        />

        <StatCard
          pending={isPending}
          label="Customer Spend"
          icon={
            <IndianRupee className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          }
          iconWrap="border-amber-500/20 bg-amber-500/10"
          value={
            <span className="text-destructive dark:text-amber-400">
              ₹{Number(usage.currentMonthSpend ?? 0).toFixed(2)}
            </span>
          }
          hint="Deducted automatically after each call"
          footer={
            <div className="flex items-center mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
              Remaining:{" "}
              <div className="font-bold tabular-nums text-foreground">
                {isPending ? (
                  <Skeleton className="h-4 w-8 rounded-full" />
                ) : (
                  <span>₹{balance.toFixed(2)}</span>
                )}
              </div>
            </div>
          }
        />
      </div>
    </div>
  );
}

function StatCard({
  label,
  icon,
  iconWrap,
  value,
  hint,
  footer,
  pending,
}: {
  label: string;
  icon: React.ReactNode;
  iconWrap: string;
  value: React.ReactNode;
  hint: string;
  footer?: React.ReactNode;
  pending?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-card p-5 shadow-sm transition-colors hover:border-border/80",
        pending && "animate-pulse opacity-70",
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <div
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg border",
            iconWrap,
          )}
        >
          {icon}
        </div>
      </div>
      <div className="text-3xl font-bold tracking-tight tabular-nums text-foreground">
        {!pending ? value : <Skeleton className="h-8 w-full rounded-full" />}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{hint}</p>
      {footer}
    </div>
  );
}
