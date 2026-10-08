"use client";

import { useMemo } from "react";
import {
  RefreshCw,
  Clock,
  IndianRupee,
  TrendingDown,
  TrendingUp,
  Info,
  PhoneCall,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import PageHeader from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import { listUsage, type UsageRow } from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtINR, shortId } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function UsagePage() {
  const {
    data: items = [],
    isPending: loading,
    error,
    refetch,
    isFetching,
  } = useQuery<UsageRow[], Error>({
    queryKey: ["usage"],
    queryFn: async () => {
      const r = await listUsage();
      return r.items;
    },
  });

  const totals = useMemo(
    () =>
      items.reduce(
        (acc, r) => ({
          billed: acc.billed + r.client_price_inr,
          cost: acc.cost + r.total_cost_inr,
          profit: acc.profit + r.profit_inr,
          seconds: acc.seconds + r.duration_seconds,
        }),
        { billed: 0, cost: 0, profit: 0, seconds: 0 },
      ),
    [items],
  );

  return (
    <div className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden">
      {/* Fixed header + metrics */}
      <div className="shrink-0 space-y-4 pb-4">
        <PageHeader
          title="Usage"
          subtitle={`Per-call cost & profit — latest ${items.length} calls`}
        >
          <Button
            variant="outline"
            size="sm"
            className="h-9"
            onClick={() => refetch()}
            disabled={loading || isFetching}
          >
            <RefreshCw
              className={`mr-2 h-3.5 w-3.5 ${
                loading || isFetching ? "animate-spin" : ""
              }`}
            />
            Refresh
          </Button>
        </PageHeader>

        {/* KPI strip */}
        {items.length > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              icon={Clock}
              label="Talk time"
              value={fmtDuration(totals.seconds)}
              iconClass="bg-blue-500/10 text-blue-600 dark:text-blue-400"
            />
            <StatCard
              icon={IndianRupee}
              label="Billed"
              value={fmtINR(totals.billed)}
              iconClass="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              valueClass="text-emerald-700 dark:text-emerald-400"
            />
            <StatCard
              icon={TrendingDown}
              label="Provider cost"
              value={fmtINR(totals.cost)}
              iconClass="bg-rose-500/10 text-rose-600 dark:text-rose-400"
              valueClass="text-rose-600 dark:text-rose-400"
            />
            <StatCard
              icon={TrendingUp}
              label="Gross profit"
              value={fmtINR(totals.profit)}
              iconClass="bg-primary/10 text-primary"
              valueClass="text-primary"
              highlight
            />
          </div>
        )}
      </div>

      {/* Table fills remaining viewport */}
      <div className="flex min-h-0 flex-1 flex-col">
        <StateBox
          loading={loading}
          error={error?.message}
          empty={items.length === 0 ? "No calls recorded yet." : null}
        >
          <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
            {/* Table toolbar */}
            <div className="flex h-10 shrink-0 items-center justify-between border-b border-border/60 bg-muted/20 px-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <PhoneCall className="h-3.5 w-3.5" />
                <span className="font-semibold text-foreground">
                  Call ledger
                </span>
              </div>
              <Badge
                variant="outline"
                className="h-5 border-border/60 bg-background px-2 text-[10px] font-semibold tabular-nums text-muted-foreground"
              >
                {items.length} {items.length === 1 ? "call" : "calls"}
              </Badge>
            </div>

            {/* Scrollable table */}
            <div className="min-h-0 flex-1 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-muted/40 backdrop-blur-md">
                  <TableRow className="border-b border-border/60 hover:bg-transparent">
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Started
                    </TableHead>
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      User
                    </TableHead>
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Agent
                    </TableHead>
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Mode
                    </TableHead>
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Duration
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      STT sec
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      LLM tk
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      TTS chars
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Billed
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Cost
                    </TableHead>
                    <TableHead className="h-9 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Profit
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((r) => {
                    const profitPositive = r.profit_inr >= 0;
                    return (
                      <TableRow
                        key={r.id}
                        className="border-b border-border/40 transition-colors hover:bg-muted/20"
                      >
                        <TableCell className="whitespace-nowrap px-4 py-2.5 text-xs tabular-nums text-muted-foreground">
                          {fmtDateTime(r.started_at)}
                        </TableCell>
                        <TableCell className="px-4 py-2.5">
                          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                            {shortId(r.user_id)}
                          </code>
                        </TableCell>
                        <TableCell className="px-4 py-2.5">
                          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                            {shortId(r.agent_id)}
                          </code>
                        </TableCell>
                        <TableCell className="px-4 py-2.5">
                          <Badge
                            variant="outline"
                            className="h-5 border-border/60 bg-muted/40 px-1.5 text-[10px] font-medium text-muted-foreground"
                          >
                            {r.mode || "voice"}
                          </Badge>
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-xs font-medium tabular-nums text-foreground">
                          {fmtDuration(r.duration_seconds)}
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-right text-xs tabular-nums text-muted-foreground">
                          {r.stt_seconds}
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-right text-xs tabular-nums text-muted-foreground">
                          <span className="text-foreground">
                            {r.llm_input_tokens}
                          </span>
                          <span className="mx-0.5 text-muted-foreground/50">
                            /
                          </span>
                          <span className="text-foreground">
                            {r.llm_output_tokens}
                          </span>
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-right text-xs tabular-nums text-muted-foreground">
                          {r.tts_chars}
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-right text-xs font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                          {fmtINR(r.client_price_inr)}
                        </TableCell>
                        <TableCell className="px-4 py-2.5 text-right text-xs font-medium tabular-nums text-rose-600 dark:text-rose-400">
                          {fmtINR(r.total_cost_inr)}
                        </TableCell>
                        <TableCell
                          className={`px-4 py-2.5 text-right text-xs font-semibold tabular-nums ${
                            profitPositive
                              ? "text-emerald-700 dark:text-emerald-400"
                              : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {profitPositive ? "+" : ""}
                          {fmtINR(r.profit_inr)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Footer hint */}
            <div className="flex shrink-0 items-start gap-2 border-t border-border/60 bg-muted/20 px-4 py-2.5">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                <span className="font-medium text-emerald-700 dark:text-emerald-400">
                  Billed
                </span>{" "}
                = customer paid.{" "}
                <span className="font-medium text-rose-600 dark:text-rose-400">
                  Cost
                </span>{" "}
                = providers charged.{" "}
                <span className="font-medium text-foreground">Profit</span> =
                billed − cost.
              </p>
            </div>
          </div>
        </StateBox>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  iconClass,
  valueClass,
  highlight = false,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  iconClass?: string;
  valueClass?: string;
  highlight?: boolean;
}) {
  return (
    <Card
      className={`border-border/60 py-0 shadow-sm ${
        highlight ? "border-primary/20 bg-primary/5" : "bg-card"
      }`}
    >
      <div className="flex items-center gap-3 p-3.5">
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
            iconClass ?? "bg-muted/50 text-muted-foreground"
          }`}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p
            className={`mt-0.5 truncate text-xl font-bold tracking-tight tabular-nums ${
              valueClass ?? "text-foreground"
            }`}
          >
            {value}
          </p>
        </div>
      </div>
    </Card>
  );
}
