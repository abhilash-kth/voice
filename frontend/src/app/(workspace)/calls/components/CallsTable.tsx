"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  History,
  RefreshCw,
  Trash2,
  Eye,
  X,
  AlertCircle,
  Headphones,
} from "lucide-react";
import { deleteCall, getCall, listCalls, type CallRecord } from "@/lib/index";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import CallDetailDialog from "./CallDetailsDialog";

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

export default function CallsTable() {
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

  const {
    data: calls = [],
    isPending: loading,
    isFetching,
    error: listError,
    refetch,
  } = useQuery({
    queryKey: ["calls"],
    queryFn: async () => {
      const res = await listCalls();
      return [...res.calls].sort((a, b) => {
        const da = new Date(a.started_at || "").getTime();
        const db = new Date(b.started_at || "").getTime();
        return db - da;
      });
    },
  });

  const { data: detail = null, isFetching: detailLoading } = useQuery({
    queryKey: ["call", activeId],
    queryFn: () => getCall(activeId!),
    enabled: Boolean(activeId),
  });

  const deleteMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.all(ids.map((id) => deleteCall(id)));
      return ids;
    },
    onSuccess: (ids) => {
      setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)));
      if (activeId && ids.includes(activeId)) setActiveId(null);
      queryClient.setQueryData<CallRecord[]>(["calls"], (old) =>
        (old ?? []).filter((c) => !ids.includes(c.id)),
      );
      ids.forEach((id) => {
        queryClient.removeQueries({ queryKey: ["call", id] });
      });
      setActionError("");
    },
    onError: (e) => setActionError((e as Error).message),
  });

  const err = actionError || (listError ? (listError as Error).message : "");
  const allSelected = calls.length > 0 && selectedIds.length === calls.length;
  const deleting = deleteMutation.isPending;

  const openDialog = (id: string) => setActiveId(id);
  const closeDialog = () => setActiveId(null);

  const deleteOne = (id: string) => {
    if (!window.confirm("Delete this call record? This cannot be undone."))
      return;
    deleteMutation.mutate([id]);
  };

  const deleteSelected = () => {
    if (
      !selectedIds.length ||
      !window.confirm(
        `Delete ${selectedIds.length} selected call record(s)? This cannot be undone.`,
      )
    ) {
      return;
    }
    deleteMutation.mutate(selectedIds);
  };

  // Derive detail values safely
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
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-5 overflow-hidden pb-4">
      {/* ── Header Toolbar ── */}
      <div className="shrink-0 space-y-4">
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-sm">
              <History className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                Call history
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Customer calls, billing, and transcripts.
              </p>
            </div>
          </div>
          <div className="flex gap-2.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 gap-2 shadow-sm"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", isFetching && "animate-spin")}
              />
              Refresh
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="h-9 gap-2 shadow-sm"
              onClick={deleteSelected}
              disabled={!selectedIds.length || deleting}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {deleting
                ? "Deleting…"
                : selectedIds.length
                  ? `Delete (${selectedIds.length})`
                  : "Delete selected"}
            </Button>
          </div>
        </div>

        {err && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive shadow-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{err}</span>
          </div>
        )}
      </div>

      {/* ── Full Width Table Enclosure ── */}
      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden border-border/60 py-0 shadow-sm">
        <div className="flex items-center justify-between border-b border-border/60 bg-muted/20 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-foreground">Call ledger</h3>
          <Badge
            variant="outline"
            className="h-5 border-border/60 bg-background px-2 text-[10px] font-semibold tabular-nums text-muted-foreground"
          >
            {calls.length} total calls
          </Badge>
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-background">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-muted/40 backdrop-blur-md">
              <TableRow className="border-b border-border/60 hover:bg-transparent">
                <TableHead className="w-10 px-5 py-3">
                  <input
                    aria-label="Select all"
                    type="checkbox"
                    className="rounded border-input"
                    checked={allSelected}
                    onChange={(e) =>
                      setSelectedIds(
                        e.target.checked ? calls.map((c) => c.id) : [],
                      )
                    }
                  />
                </TableHead>
                <TableHead className="px-4 py-3 text-xs font-semibold text-muted-foreground">
                  Call Identity
                </TableHead>
                <TableHead className="px-4 py-3 text-xs font-semibold text-muted-foreground">
                  Timestamp
                </TableHead>
                <TableHead className="px-4 py-3 text-xs font-semibold text-muted-foreground">
                  Mode
                </TableHead>
                <TableHead className="px-4 py-3 text-xs font-semibold text-muted-foreground">
                  Status
                </TableHead>
                <TableHead className="px-4 py-3 text-xs font-semibold text-muted-foreground">
                  Duration
                </TableHead>
                <TableHead className="px-4 py-3 text-right text-xs font-semibold text-muted-foreground">
                  Rate/min
                </TableHead>
                <TableHead className="px-4 py-3 text-right text-xs font-semibold text-muted-foreground">
                  Total
                </TableHead>
                <TableHead className="px-5 py-3 text-right text-xs font-semibold text-muted-foreground">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="p-8 text-center text-sm text-muted-foreground"
                  >
                    Loading call history…
                  </TableCell>
                </TableRow>
              )}
              {!loading && calls.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="p-8 text-center text-sm text-muted-foreground"
                  >
                    No calls recorded yet.
                  </TableCell>
                </TableRow>
              )}
              {calls.map((c) => {
                const cCost = (c.cost || {}) as Record<string, unknown>;
                const billed =
                  (cCost.client_price_inr as number | undefined) ??
                  (cCost.clientPrice as number | undefined) ??
                  0;
                const rate =
                  (cCost.client_bill_per_min as number | string | undefined) ??
                  (cCost.client_rate_per_min as number | string | undefined) ??
                  (cCost.billPerMin as number | string | undefined) ??
                  "—";

                return (
                  <TableRow
                    key={c.id}
                    onClick={() => openDialog(c.id)}
                    className="cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/30"
                  >
                    <TableCell className="px-5 py-3">
                      <input
                        aria-label={`Select ${c.id}`}
                        type="checkbox"
                        className="rounded border-input"
                        onClick={(e) => e.stopPropagation()}
                        checked={selectedIds.includes(c.id)}
                        onChange={(e) =>
                          setSelectedIds((ids) =>
                            e.target.checked
                              ? [...ids, c.id]
                              : ids.filter((id) => id !== c.id),
                          )
                        }
                      />
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      <span className="font-mono text-xs font-medium text-foreground">
                        {c.id.slice(0, 12)}…
                      </span>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {c.agent_id?.slice(0, 12) || "agent"}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-4 py-3 text-xs tabular-nums text-muted-foreground">
                      {formatDate(c.started_at)}
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className="h-5 border-border/60 bg-muted/30 px-2 text-[10px] capitalize text-muted-foreground"
                      >
                        {c.mode}
                      </Badge>
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className={cn(
                          "h-5 px-2 text-[10px] font-semibold capitalize",
                          statusClass(c.status),
                        )}
                      >
                        {c.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="px-4 py-3 text-xs font-medium tabular-nums text-foreground">
                      {formatDuration(c.duration_seconds)}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-right text-xs tabular-nums text-muted-foreground">
                      ₹{rate}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-right text-xs font-semibold tabular-nums text-foreground">
                      ₹{billed}
                    </TableCell>
                    <TableCell className="px-5 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-8 gap-1.5 px-3 text-xs font-medium transition-colors hover:bg-primary/10 hover:text-primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            openDialog(c.id);
                          }}
                        >
                          <Eye className="h-3.5 w-3.5" />
                          View
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-8 px-2.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          disabled={deleting}
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteOne(c.id);
                          }}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </Card>

      <CallDetailDialog
        open={activeId !== null}
        onOpenChange={(open) => {
          if (!open) setActiveId(null);
        }}
        detail={detail}
        loading={Boolean(activeId) && detailLoading && !detail}
      />
    </div>
  );
}
