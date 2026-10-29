"use client";

import { useMemo, useState } from "react";
import {
  RefreshCw,
  Clock,
  IndianRupee,
  TrendingDown,
  TrendingUp,
  Info,
  PhoneCall,
  PhoneOff,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import PageHeader from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import { endAdminCall, listUsage, type UsageRow } from "@/lib/api";
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
    refetchInterval: 10000,
  });

  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const endCallMutation = useMutation({
    mutationFn: endAdminCall,
    onMutate: () => {
      setNotice("");
      setActionError("");
    },
    onSuccess: async (result) => {
      setNotice(
        result.already_ended
          ? `Call ${shortId(result.call_id)} was already ${result.status}.`
          : `Call ${shortId(result.call_id)} ended and marked ${result.status}.`,
      );
      await queryClient.invalidateQueries({ queryKey: ["usage"] });
    },
    onError: (mutationError) => {
      setActionError(
        mutationError instanceof Error
          ? mutationError.message
          : "Could not end this call.",
      );
    },
  });
  const endingCallId = endCallMutation.isPending
    ? String(endCallMutation.variables || "")
    : "";

  const handleEndCall = (row: UsageRow) => {
    const destination = row.phone ? ` to ${row.phone}` : "";
    if (
      window.confirm(
        `End this ${row.status} ${row.mode || "voice"} call${destination}? If it is still live, its LiveKit room will be disconnected. If it is stale, its status will be corrected so the customer can start another call.`,
      )
    ) {
      endCallMutation.mutate(row.id);
    }
  };

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
        {notice && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{notice}</span>
          </div>
        )}
        {actionError && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2.5 text-sm font-medium text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{actionError}</span>
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
                      Status
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
                    <TableHead className="h-9 px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Action
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((r) => {
                    const profitPositive = r.profit_inr >= 0;
                    const isActiveCall =
                      r.status === "planned" || r.status === "in-progress";
                    const isEndingCall = endingCallId === r.id;
                    return (
                      <TableRow
                        key={r.id}
                        className="border-b border-border/40 transition-colors hover:bg-muted/20"
                      >
                        <TableCell className="whitespace-nowrap px-4 py-2.5 text-xs tabular-nums text-muted-foreground">
                          <p>{fmtDateTime(r.started_at)}</p>
                          {r.phone && (
                            <p className="mt-0.5 font-mono text-[11px] text-foreground/80">
                              {r.phone}
                            </p>
                          )}
                        </TableCell>
                        <TableCell className="px-4 py-2.5">
                          <p className="max-w-[180px] truncate text-xs font-medium text-foreground">
                            {r.user_name || r.user_email || shortId(r.user_id)}
                          </p>
                          {(r.user_name || r.user_email) && (
                            <p className="mt-0.5 max-w-[180px] truncate font-mono text-[11px] text-muted-foreground">
                              {r.user_email || shortId(r.user_id)}
                            </p>
                          )}
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
                        <TableCell className="whitespace-nowrap px-4 py-2.5">
                          <CallStatusBadge status={r.status} />
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
                        <TableCell className="whitespace-nowrap px-4 py-2.5">
                          {isActiveCall ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="destructive"
                              className="h-8 gap-1.5 text-xs"
                              disabled={isEndingCall}
                              onClick={() => handleEndCall(r)}
                            >
                              {isEndingCall ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <PhoneOff className="h-3.5 w-3.5" />
                              )}
                              {isEndingCall ? "Ending…" : "End call"}
                            </Button>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
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
                billed − cost. For a planned/in-progress row,{" "}
                <span className="font-medium text-foreground">End call</span>{" "}
                disconnects a live room or corrects a stale active status.
              </p>
            </div>
          </div>
        </StateBox>
      </div>
    </div>
  );
}

function CallStatusBadge({ status }: { status: string }) {
  const className =
    status === "completed"
      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
      : status === "failed"
        ? "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-400"
        : status === "planned" || status === "in-progress"
          ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
          : "border-border/60 bg-muted/40 text-muted-foreground";

  return (
    <Badge
      variant="outline"
      className={`h-5 px-2 text-[10px] font-semibold capitalize ${className}`}
    >
      {(status || "unknown").replace("-", " ")}
    </Badge>
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
