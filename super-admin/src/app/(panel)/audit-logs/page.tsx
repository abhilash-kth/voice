"use client";

import React, { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Search,
  ScrollText,
  ChevronDown,
  ChevronUp,
  X,
  Code2,
} from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import Pager from "@/components/Pager";
import { listAuditLogs, type AuditLog, type Paged } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery, keepPreviousData } from "@tanstack/react-query";

function parsePage(v: string | null) {
  const n = Number(v || "1");
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
}

function getActionBadge(action: string) {
  if (action.includes("deleted") || action.includes("disabled")) {
    return (
      <Badge
        variant="outline"
        className="border-rose-500/20 bg-rose-500/10 text-[10px] font-mono text-rose-600 dark:text-rose-400"
      >
        {action}
      </Badge>
    );
  }
  if (
    action.includes("created") ||
    action.includes("enabled") ||
    action.includes("adjusted") ||
    action.includes("billing")
  ) {
    return (
      <Badge
        variant="outline"
        className="border-emerald-500/20 bg-emerald-500/10 text-[10px] font-mono text-emerald-600 dark:text-emerald-400"
      >
        {action}
      </Badge>
    );
  }
  if (
    action.includes("updated") ||
    action.includes("rotated") ||
    action.includes("model_")
  ) {
    return (
      <Badge
        variant="outline"
        className="border-amber-500/20 bg-amber-500/10 text-[10px] font-mono text-amber-600 dark:text-amber-400"
      >
        {action}
      </Badge>
    );
  }
  if (action.includes("super_admin")) {
    return (
      <Badge
        variant="outline"
        className="border-purple-500/20 bg-purple-500/10 text-[10px] font-mono text-purple-600 dark:text-purple-400"
      >
        {action}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="bg-muted/40 text-[10px] font-mono text-muted-foreground">
      {action}
    </Badge>
  );
}

export default function AuditLogsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // URL search params as source of truth
  const q = searchParams.get("q") || "";
  const targetType = searchParams.get("target_type") || "";
  const pageL = parsePage(searchParams.get("page"));

  const [expanded, setExpanded] = useState<string | null>(null);

  // Local draft for search input
  const [qDraft, setQDraft] = useState(q);
  useEffect(() => {
    setQDraft(q);
  }, [q]);

  const setParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(patch).forEach(([key, value]) => {
        if (value === null || value === undefined || value === "") {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams]
  );

  const {
    data,
    isPending: loading,
    error,
  } = useQuery<Paged<AuditLog>, Error>({
    queryKey: ["audit-logs", { page: pageL, q, targetType }],
    queryFn: () =>
      listAuditLogs({
        page: pageL,
        page_size: 50,
        q: q || undefined,
        target_type: targetType || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  // Debounce search input to URL updates
  useEffect(() => {
    const t = setTimeout(() => {
      if (qDraft === q) return;
      setParams({ q: qDraft || null, page: "1" });
    }, 300);
    return () => clearTimeout(t);
  }, [qDraft, q, setParams]);

  const hasActiveFilters = Boolean(q || targetType);

  const clearFilters = () => {
    setQDraft("");
    setParams({ q: null, target_type: null, page: "1" });
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-0">
      <div className="shrink-0">
        <PageHeader
          title="Audit logs"
          subtitle="Every admin mutation — who, what, when"
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <StateBox
          loading={loading}
          error={error?.message}
          empty={
            data && data.items.length === 0
              ? "No audit entries yet — they appear after the first admin action."
              : null
          }
        >
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden border border-border/60 shadow-xs py-0">
            {/* Integrated Toolbar Header */}
            <div className="flex h-12 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-card px-2">
              <div className="flex items-center gap-2">
                {/* Search Input */}
                <div className="relative w-64">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="h-8 pl-8 pr-7 text-xs"
                    placeholder="Search admin, action, or target…"
                    value={qDraft}
                    onChange={(e) => setQDraft(e.target.value)}
                  />
                  {qDraft && (
                    <button
                      type="button"
                      onClick={() => {
                        setQDraft("");
                        setParams({ q: null, page: "1" });
                      }}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>

                {/* Target Type Filter */}
                <Select
                  value={targetType || "all"}
                  onValueChange={(val) =>
                    setParams({
                      target_type: val === "all" ? null : val,
                      page: "1",
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <span className="mr-1 text-muted-foreground">Target:</span>
                    <SelectValue placeholder="All target types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all" className="text-xs">
                      All target types
                    </SelectItem>
                    <SelectItem value="user" className="text-xs">
                      user
                    </SelectItem>
                    <SelectItem value="provider" className="text-xs">
                      provider
                    </SelectItem>
                    <SelectItem value="model" className="text-xs">
                      model
                    </SelectItem>
                    <SelectItem value="credential" className="text-xs">
                      credential
                    </SelectItem>
                    <SelectItem value="billing" className="text-xs">
                      billing
                    </SelectItem>
                  </SelectContent>
                </Select>

                {/* Reset Filters */}
                {hasActiveFilters && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={clearFilters}
                    className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <X className="mr-1 h-3 w-3" />
                    Reset
                  </Button>
                )}
              </div>

              {/* Total Entries Count */}
              {data && (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
                  <ScrollText className="h-3.5 w-3.5" />
                  <span>
                    Total <strong className="font-semibold text-foreground">{data.total}</strong> entries
                  </span>
                </div>
              )}
            </div>

            {/* Scrollable Table Area */}
            <div className="min-h-0 flex-1 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-card shadow-xs">
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="h-8 py-0 text-[10px] font-semibold">When</TableHead>
                    <TableHead className="h-8 py-0 text-[10px] font-semibold">Admin</TableHead>
                    <TableHead className="h-8 py-0 text-[10px] font-semibold">Action</TableHead>
                    <TableHead className="h-8 py-0 text-[10px] font-semibold">Target</TableHead>
                    <TableHead className="h-8 py-0 text-right text-[10px] font-semibold">Details</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.items.map((l) => {
                    const isExpanded = expanded === l.id;
                    const hasDetails = Object.keys(l.detail || {}).length > 0;

                    return (
                      <React.Fragment key={l.id}>
                        <TableRow className="transition-colors hover:bg-muted/20">
                          <TableCell className="py-2 whitespace-nowrap text-[11px] tabular-nums text-muted-foreground">
                            {fmtDateTime(l.created_at)}
                          </TableCell>
                          <TableCell className="py-2 text-xs font-medium text-foreground">
                            {l.admin_email || <span className="text-muted-foreground/60">—</span>}
                          </TableCell>
                          <TableCell className="py-2">
                            {getActionBadge(l.action)}
                          </TableCell>
                          <TableCell className="py-2 text-xs">
                            <Badge
                              variant="outline"
                              className="mr-1.5 border-border bg-muted/30 text-[10px] font-normal text-muted-foreground"
                            >
                              {l.target_type}
                            </Badge>
                            <code className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[10px] text-muted-foreground">
                              {l.target_id.slice(0, 12)}
                              {l.target_id.length > 12 ? "…" : ""}
                            </code>
                          </TableCell>
                          <TableCell className="py-2 text-right">
                            {hasDetails && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-[11px] text-muted-foreground hover:text-foreground"
                                onClick={() =>
                                  setExpanded(isExpanded ? null : l.id)
                                }
                              >
                                <Code2 className="mr-1 h-3 w-3" />
                                {isExpanded ? "Hide" : "Detail"}
                                {isExpanded ? (
                                  <ChevronUp className="ml-1 h-3 w-3" />
                                ) : (
                                  <ChevronDown className="ml-1 h-3 w-3" />
                                )}
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>

                        {/* Inline Detail Expansion Drawer */}
                        {isExpanded && (
                          <TableRow className="bg-muted/10 hover:bg-muted/10">
                            <TableCell colSpan={5} className="p-3">
                              <div className="rounded-lg border border-border/60 bg-muted/30 p-3 shadow-inner">
                                <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                                  <Code2 className="h-3 w-3" />
                                  <span>Mutation details</span>
                                </div>
                                <pre className="max-h-48 overflow-auto rounded-md bg-background/80 p-2.5 font-mono text-[11px] leading-relaxed text-foreground shadow-xs">
                                  {JSON.stringify(l.detail ?? {}, null, 2)}
                                </pre>
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </React.Fragment>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Pinned Pagination Footer */}
            {data && (
              <div className="shrink-0">
                <Pager
                  total={data.total}
                  page={data.page}
                  pageSize={data.page_size}
                  onPage={(p) => setParams({ page: String(p) })}
                />
              </div>
            )}
          </Card>
        </StateBox>
      </div>
    </div>
  );
}