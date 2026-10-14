"use client";

import { useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, ReceiptText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Tx {
  ts: string;
  kind: string;
  amount: number;
  note?: string;
}

type TransactionFilter = "all" | "topups" | "spent";

export default function RecentTransactions({
  transactions,
}: {
  transactions: Tx[];
}) {
  const [filter, setFilter] = useState<TransactionFilter>("all");

  // Keep the existing behavior of showing at most the latest 20 transactions.
  const recentTransactions = useMemo(
    () => transactions.slice(0, 20),
    [transactions],
  );

  const filteredTransactions = useMemo(() => {
    if (filter === "topups") {
      return recentTransactions.filter(
        (transaction) => transaction.kind === "recharge",
      );
    }

    if (filter === "spent") {
      return recentTransactions.filter(
        (transaction) => transaction.kind === "spend",
      );
    }

    return recentTransactions;
  }, [filter, recentTransactions]);

  const counts = {
    all: recentTransactions.length,
    topups: recentTransactions.filter(
      (transaction) => transaction.kind === "recharge",
    ).length,
    spent: recentTransactions.filter(
      (transaction) => transaction.kind === "spend",
    ).length,
  };

  const formatDate = (ts: string) => {
    try {
      const date = new Date(ts.replace(/-/g, "/").replace(" ", "T") || ts);
      if (isNaN(date.getTime())) return ts;

      return date.toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  const filters: { value: TransactionFilter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "topups", label: "Top-ups" },
    { value: "spent", label: "Spent" },
  ];

  return (
    <section
      aria-labelledby="recent-transactions-title"
      className="w-full min-w-0 overflow-hidden rounded-2xl border border-border bg-orange-50 p-4 shadow-sm sm:p-5"
    >
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-200 text-orange-700">
            <ReceiptText className="h-4 w-4" />
          </div>

          <div className="min-w-0">
            <h2
              id="recent-transactions-title"
              className="text-sm font-semibold tracking-tight text-foreground"
            >
              Recent transactions
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {transactions.length} total records
            </p>
          </div>
        </div>

        <div
          className="flex w-fit items-center gap-1 rounded-lg bg-background p-1"
          aria-label="Filter transactions"
        >
          {filters.map(({ value, label }) => (
            <Button
              key={value}
              type="button"
              size="sm"
              variant={filter === value ? "secondary" : "ghost"}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "h-7 gap-1.5 px-2.5 text-xs",
                filter === value && "shadow-sm",
              )}
            >
              {label}
              <span className="text-[10px] text-muted-foreground">
                {counts[value]}
              </span>
            </Button>
          ))}
        </div>
      </header>

      {transactions.length === 0 ? (
        <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-background px-4 text-center">
          <ReceiptText className="mb-2 h-5 w-5 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">
            No transactions yet
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Recharge or make a call to see your history.
          </p>
        </div>
      ) : (
        <div className="max-h-[420px] overflow-auto rounded-xl border border-border">
          <table className="w-full min-w-[820px] table-fixed text-left">
            <colgroup>
              <col className="w-[220px]" />
              <col className="w-[170px]" />
              <col />
              <col className="w-[145px]" />
            </colgroup>

            <thead className="sticky top-0 z-10 border-b border-border bg-background text-[10px] font-semibold uppercase tracking-wider text-muted-foreground backdrop-blur">
              <tr>
                <th scope="col" className="px-3 py-2.5">
                  Type
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Date
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Details
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Amount
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-border">
              {filteredTransactions.length === 0 ? (
                <tr>
                  <td
                    colSpan={4}
                    className="px-3 py-8 text-center text-xs text-muted-foreground"
                  >
                    No {filter === "topups" ? "top-ups" : "spending"} in recent
                    transactions.
                  </td>
                </tr>
              ) : (
                filteredTransactions.map((transaction, index) => {
                  const isSpend = transaction.kind === "spend";

                  return (
                    <tr
                      key={`${transaction.ts}-${transaction.kind}-${index}`}
                      className="h-12 transition-colors bg-background"
                    >
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border",
                              isSpend
                                ? "border-rose-500/20 bg-rose-500/10 text-rose-600 dark:text-rose-400"
                                : "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
                            )}
                          >
                            {isSpend ? (
                              <ArrowUpRight className="h-3.5 w-3.5" />
                            ) : (
                              <ArrowDownLeft className="h-3.5 w-3.5" />
                            )}
                          </span>

                          <span className="whitespace-nowrap text-xs font-medium text-foreground">
                            {isSpend ? "Call charge" : "Wallet top-up"}
                          </span>

                          <span
                            className={cn(
                              "whitespace-nowrap rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase leading-none",
                              isSpend
                                ? "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                                : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
                            )}
                          >
                            {transaction.kind}
                          </span>
                        </div>
                      </td>

                      <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                        {formatDate(transaction.ts)}
                      </td>

                      <td
                        className="truncate px-3 py-2 text-xs text-muted-foreground"
                        title={transaction.note || ""}
                      >
                        {transaction.note || "—"}
                      </td>

                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        <span
                          className={cn(
                            "text-xs font-semibold tabular-nums",
                            isSpend
                              ? "text-rose-600 dark:text-rose-400"
                              : "text-emerald-600 dark:text-emerald-400",
                          )}
                        >
                          {isSpend ? "−" : "+"}₹
                          {Math.abs(transaction.amount).toFixed(2)}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
