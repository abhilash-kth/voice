"use client";

import { Headphones, AlertCircle } from "lucide-react";
import type { CallRecord } from "@/lib/index";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

function formatDuration(sec: number) {
  if (!sec) return "0s";
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

function formatDate(d: string) {
  try {
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return d;
  }
}

function statusClass(status: string) {
  if (status === "completed")
    return "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  if (status === "in-progress")
    return "border-blue-500/25 bg-blue-500/10 text-blue-700 animate-pulse dark:text-blue-400";
  if (status === "failed")
    return "border-destructive/25 bg-destructive/10 text-destructive";
  return "border-border/60 bg-muted/40 text-muted-foreground";
}

export interface CallDetailDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  detail: CallRecord | null;
  loading?: boolean;
}

export default function CallDetailDialog({
  open,
  onOpenChange,
  detail,
  loading = false,
}: CallDetailDialogProps) {
  const cost = detail?.cost as Record<string, unknown> | null | undefined;
  const totalBilled =
    (cost?.client_price_inr as number | undefined) ??
    (cost?.clientPrice as number | undefined) ??
    0;
  const ratePerMin =
    (cost?.client_bill_per_min as number | undefined) ??
    (cost?.client_rate_per_min as number | undefined) ??
    (cost?.billPerMin as number | undefined) ??
    (cost?.clientRatePerMin as number | undefined) ??
    0;
  const durationMins =
    (cost?.duration_mins as number | string | undefined) ??
    (cost?.durationMins as number | string | undefined) ??
    (detail ? (detail.duration_seconds / 60).toFixed(2) : 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[80vh] w-[90vw] max-w-2xl flex-col gap-0 overflow-auto p-0 sm:max-w-3xl">
        <DialogHeader className="shrink-0 border-b border-border/60 bg-muted/20 px-6 py-5">
          <DialogTitle className="text-lg font-bold tracking-tight">
            Call details
          </DialogTitle>
          <DialogDescription className="text-xs">
            Billing and transcript summary for the selected session.
          </DialogDescription>
        </DialogHeader>

        {loading && !detail ? (
          <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
            Loading details…
          </div>
        ) : !detail ? (
          <div className="flex h-64 flex-col items-center justify-center gap-2 px-6 text-center">
            <AlertCircle className="h-5 w-5 text-destructive" />
            <p className="text-sm font-medium text-destructive">
              Could not load call details.
            </p>
          </div>
        ) : (
          <ScrollArea className="flex-1 px-6 py-6">
            <div className="space-y-6 pr-3">
              {/* Meta */}
              <div className="flex flex-wrap gap-2">
                <Badge
                  variant="outline"
                  className="h-6 border-border/60 bg-muted/40 px-2 font-mono text-[10px] text-muted-foreground"
                >
                  ID: {detail.id}
                </Badge>
                <Badge
                  variant="outline"
                  className="h-6 border-border/60 bg-muted/40 px-2 text-[10px] capitalize text-muted-foreground"
                >
                  {detail.mode}
                </Badge>
                <Badge
                  variant="outline"
                  className={cn(
                    "h-6 px-2 text-[10px] font-semibold capitalize",
                    statusClass(detail.status),
                  )}
                >
                  {detail.status}
                </Badge>
                {detail.recording_url && (
                  <a
                    href={detail.recording_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-6 items-center gap-1.5 rounded-full border border-blue-500/25 bg-blue-500/10 px-3 text-[10px] font-semibold text-blue-700 hover:bg-blue-500/15 dark:text-blue-400"
                  >
                    <Headphones className="h-3 w-3" />
                    Recording
                  </a>
                )}
              </div>

              {/* Billing */}
              <div className="rounded-xl border border-border/60 bg-muted/15 p-5">
                <p className="mb-3.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Billing summary
                </p>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-border/60 bg-background p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Duration
                    </p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-foreground">
                      {formatDuration(detail.duration_seconds)}
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {durationMins} billable min
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Rate
                    </p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-primary">
                      ₹{ratePerMin}
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      per minute
                    </p>
                  </div>
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700/80 dark:text-emerald-400/80">
                      Total billed
                    </p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-emerald-700 dark:text-emerald-400">
                      ₹{totalBilled}
                    </p>
                    <p className="mt-1 text-[11px] text-emerald-700/70 dark:text-emerald-400/70">
                      customer charge
                    </p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                  <span>Started {formatDate(detail.started_at)}</span>
                  {detail.ended_at && (
                    <span>· Ended {formatDate(detail.ended_at)}</span>
                  )}
                </div>
              </div>

              {/* Transcript */}
              <div>
                <div className="mb-4 flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Transcript
                  </p>
                  <Badge
                    variant="outline"
                    className="h-5 border-border/60 bg-muted/40 px-2 text-[10px] text-muted-foreground"
                  >
                    {detail.transcripts.length} messages
                  </Badge>
                </div>
                <div className="space-y-3 pb-2">
                  {detail.transcripts.length === 0 && (
                    <p className="rounded-xl border border-border/60 bg-muted/20 p-6 text-center text-sm text-muted-foreground">
                      No transcript recorded.
                    </p>
                  )}
                  {detail.transcripts.map((t, i) => {
                    const isUser = t.role === "user";
                    return (
                      <div
                        key={i}
                        className={cn(
                          "rounded-2xl border px-4 py-3.5 text-[14px]",
                          isUser
                            ? "ml-8 border-primary/20 bg-primary/10 text-foreground"
                            : "mr-8 border-border/60 bg-muted/30 text-foreground",
                        )}
                      >
                        <span
                          className={cn(
                            "mb-2 inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                            isUser
                              ? "bg-primary/20 text-primary"
                              : "bg-muted text-muted-foreground",
                          )}
                        >
                          {isUser ? "Customer" : "Agent"}
                        </span>
                        <p className="leading-relaxed">{t.text}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
}
