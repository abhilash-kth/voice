"use client";

import { useCallback, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  Edit3,
  Trash2,
  CheckCircle2,
  XCircle,
  Info,
  Power,
  Cpu,
  Mic,
  Volume2,
  PhoneCall,
} from "lucide-react";
import PageHeader, { useBusy } from "@/components/PageHeader";
import Pager from "@/components/Pager";
import ModelFormModal from "@/components/ModelFormModal";
import {
  listModels,
  updateModel,
  deleteModel,
  type CatalogModel,
  type Paged,
} from "@/lib/api";
import { fmtINR } from "@/lib/format";
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
import { StateBox } from "@/components/StateBox";
import { useQuery, keepPreviousData } from "@tanstack/react-query";

const KINDS = ["llm", "stt", "tts", "telephony"] as const;

const KIND_ICONS: Record<(typeof KINDS)[number], React.ElementType> = {
  llm: Cpu,
  stt: Mic,
  tts: Volume2,
  telephony: PhoneCall,
};

function parsePage(v: string | null) {
  const n = Number(v || "1");
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
}

function parseKind(v: string | null): (typeof KINDS)[number] {
  if (v && (KINDS as readonly string[]).includes(v)) {
    return v as (typeof KINDS)[number];
  }
  return "llm";
}

export default function ModelsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const kind = parseKind(searchParams.get("kind"));
  const page = parsePage(searchParams.get("page"));

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<CatalogModel | null>(null);
  const { busy, msg, err, run } = useBusy();

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
    [router, pathname, searchParams],
  );

  const {
    data,
    isPending: loading,
    error,
    refetch,
  } = useQuery<Paged<CatalogModel>, Error>({
    queryKey: ["models", { kind, page }],
    queryFn: () => listModels({ kind, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  const toggle = (m: CatalogModel) =>
    run(
      () => updateModel(m.id, { enabled: !m.enabled }),
      m.enabled ? "Model disabled" : "Model enabled ✓",
    ).then((ok) => {
      if (ok !== undefined) refetch();
    });

  const remove = (m: CatalogModel) => {
    if (
      !window.confirm(
        `Delete model "${m.display_name}" (${m.catalog_id})?\n\nAgents currently using it will fall back to their configured fallback.`,
      )
    )
      return;
    run(() => deleteModel(m.id), "Model deleted ✓").then((ok) => {
      if (ok !== undefined) refetch();
    });
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="shrink-0">
        <PageHeader
          title="Catalog models"
          subtitle="What customers can pick per agent — pricing, tiers, availability"
        >
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Add model
          </Button>
        </PageHeader>

        {(msg || err) && (
          <div
            className={`mb-4 flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium ${
              msg
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-destructive/20 bg-destructive/10 text-destructive"
            }`}
          >
            {msg ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <XCircle className="h-4 w-4 shrink-0 text-destructive" />
            )}
            <span>{msg || err}</span>
          </div>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <StateBox
          loading={loading}
          error={error?.message}
          empty={
            data && data.items.length === 0
              ? `No ${kind.toUpperCase()} models yet.`
              : null
          }
        >
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden border border-border/60 shadow-sm py-0">
            {/* Header toolbar integrated into Card */}
            <div className="flex shrink-0 items-center justify-between border-b border-border/60 bg-card px-2 py-2">
              <div className="flex items-center gap-1">
                {KINDS.map((k) => {
                  const Icon = KIND_ICONS[k];
                  const active = kind === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setParams({ kind: k, page: "1" })}
                      className={`flex h-7 items-center gap-2 rounded-md px-3 text-xs font-semibold uppercase tracking-wider transition-all ${
                        active
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                      }`}
                    >
                      <Icon className="h-3 w-3" />
                      <span>{k}</span>
                    </button>
                  );
                })}
              </div>

              {data && (
                <div className="text-[11px] text-muted-foreground tabular-nums">
                  Total{" "}
                  <span className="font-semibold text-foreground">
                    {data.total}
                  </span>{" "}
                  models
                </div>
              )}
            </div>

            {/* Scrollable table */}
            <div className="min-h-0 flex-1 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-card shadow-xs">
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="py-2.5 font-semibold text-xs">
                      Model
                    </TableHead>
                    <TableHead className="py-2.5 font-semibold text-xs">
                      Provider
                    </TableHead>
                    <TableHead className="py-2.5 font-semibold text-xs">
                      Tier
                    </TableHead>
                    <TableHead className="py-2.5 text-right font-semibold text-xs">
                      Customer ₹/min
                    </TableHead>
                    <TableHead className="py-2.5 text-right font-semibold text-xs">
                      Cost
                    </TableHead>
                    <TableHead className="py-2.5 font-semibold text-xs">
                      Status
                    </TableHead>
                    <TableHead className="py-2.5 text-right font-semibold text-xs">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.items.map((m) => (
                    <TableRow key={m.id} className="transition-colors">
                      <TableCell className="py-2">
                        <div className="font-semibold text-[13px] text-foreground">
                          {m.display_name}
                        </div>
                        <div className="text-[11px] font-mono text-muted-foreground">
                          {m.catalog_id}
                          {m.model_id && m.model_id !== m.catalog_id
                            ? ` → ${m.model_id}`
                            : ""}
                        </div>
                      </TableCell>
                      <TableCell className="py-2">
                        <Badge
                          variant="outline"
                          className="bg-muted/30 font-mono text-[10px] font-medium text-muted-foreground"
                        >
                          {m.provider_slug}
                        </Badge>
                      </TableCell>
                      <TableCell className="py-2">
                        <Badge
                          variant="outline"
                          className={`text-[10px] px-1.5 h-4 ${
                            m.tier === "free"
                              ? "border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                              : "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                          }`}
                        >
                          {m.tier}
                        </Badge>
                      </TableCell>
                      <TableCell className="py-2 text-right font-semibold tabular-nums text-[13px] text-foreground">
                        {fmtINR(m.customer_price_per_min)}
                      </TableCell>
                      <TableCell className="py-2 text-right text-[11px] tabular-nums text-muted-foreground">
                        {m.kind === "llm"
                          ? `₹${m.input_price_per_1m}/₹${m.output_price_per_1m} per 1M`
                          : m.kind === "tts"
                            ? `₹${m.cost_per_1k_chars}/1K chars`
                            : `₹${m.cost_per_min}/min`}
                      </TableCell>
                      <TableCell className="py-2">
                        {m.enabled ? (
                          <Badge
                            variant="outline"
                            className="gap-1.5 border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-1.5 h-5 text-[10px]"
                          >
                            <span className="h-1 w-1 animate-pulse rounded-full bg-emerald-500" />
                            Live
                          </Badge>
                        ) : (
                          <Badge
                            variant="outline"
                            className="gap-1.5 border-border bg-muted text-muted-foreground px-1.5 h-5 text-[10px]"
                          >
                            <span className="h-1 w-1 rounded-full bg-muted-foreground/40" />
                            Hidden
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="py-2 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => toggle(m)}
                            className="h-7 px-2 text-[11px]"
                          >
                            <Power className="mr-1 h-3 w-3" />
                            {m.enabled ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setEditing(m)}
                            className="h-7 px-2 text-[11px]"
                          >
                            <Edit3 className="mr-1 h-3 w-3" />
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => remove(m)}
                            className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pinned pagination */}
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

          <div className="mt-3 flex shrink-0 items-start gap-2.5 rounded-lg border border-border/50 bg-muted/20 p-2.5 text-[11px] text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
            <p className="leading-relaxed">
              Hidden models are not shown to customers. Customer ₹/min is what
              users are billed; Cost is what the provider charges you (internal
              only).
            </p>
          </div>
        </StateBox>
      </div>

      {showCreate && (
        <ModelFormModal
          model={null}
          defaultKind={kind}
          onClose={() => setShowCreate(false)}
          onSaved={() => refetch()}
        />
      )}
      {editing && (
        <ModelFormModal
          model={editing}
          defaultKind={kind}
          onClose={() => setEditing(null)}
          onSaved={() => refetch()}
        />
      )}
    </div>
  );
}
