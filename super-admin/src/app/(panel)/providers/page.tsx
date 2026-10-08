"use client";

import { useState } from "react";
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
  Link2,
} from "lucide-react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import PageHeader, { useBusy } from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import ProviderFormModal from "@/components/ProviderFormModal";
import {
  listProviders,
  updateProvider,
  deleteProvider,
  type Provider,
} from "@/lib/api";
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

const KINDS = ["llm", "stt", "tts", "telephony"] as const;

const KIND_ICONS: Record<(typeof KINDS)[number], React.ElementType> = {
  llm: Cpu,
  stt: Mic,
  tts: Volume2,
  telephony: PhoneCall,
};

export default function ProvidersPage() {
  const [kind, setKind] = useState<string>("llm");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const { busy, msg, err, run } = useBusy();

  const {
    data: items = [],
    isPending: loading,
    error,
    refetch,
  } = useQuery<Provider[], Error>({
    queryKey: ["providers", { kind }],
    queryFn: async () => {
      const r = await listProviders(kind);
      return r.items;
    },
    placeholderData: keepPreviousData,
  });

  const toggle = (p: Provider) =>
    run(
      () => updateProvider(p.id, { enabled: !p.enabled }),
      p.enabled ? "Provider disabled" : "Provider enabled ✓"
    ).then((ok) => {
      if (ok !== undefined) refetch();
    });

  const remove = (p: Provider) => {
    if (!window.confirm(`Delete provider "${p.slug}" (${p.kind})?`)) return;
    const cascade = window.confirm(
      "Also DELETE all catalog models belonging to this provider?\n\nOK = delete provider + its models\nCancel = delete provider only (fails if it still has models)"
    );
    run(() => deleteProvider(p.id, cascade), "Provider deleted ✓").then((ok) => {
      if (ok !== undefined) refetch();
    });
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="shrink-0">
        <PageHeader
          title="Providers"
          subtitle="Platform integrations — adapters, endpoints, availability"
        >
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Add provider
          </Button>
        </PageHeader>

        {(msg || err) && (
          <div
            className={`mb-4 flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium ${
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
            items.length === 0
              ? `No ${kind.toUpperCase()} providers yet.`
              : null
          }
        >
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden border border-border/60 shadow-sm py-0">
            {/* Kind tabs + count */}
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-card px-4 py-2.5">
              <div className="inline-flex rounded-lg border border-border/60 bg-muted/40 p-1">
                {KINDS.map((k) => {
                  const Icon = KIND_ICONS[k];
                  const active = kind === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setKind(k)}
                      className={`flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-semibold uppercase tracking-wider transition-all ${
                        active
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Icon className="h-3 w-3" />
                      <span>{k}</span>
                    </button>
                  );
                })}
              </div>

              <div className="text-[11px] tabular-nums text-muted-foreground">
                <span className="font-semibold text-foreground">
                  {items.length}
                </span>{" "}
                {items.length === 1 ? "provider" : "providers"}
              </div>
            </div>

            {/* Scrollable table */}
            <div className="min-h-0 flex-1 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Provider
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Adapter
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Base URL
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Key env
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Tier
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Status
                    </TableHead>
                    <TableHead className="py-2.5 text-right text-xs font-semibold">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((p) => (
                    <TableRow key={p.id} className="transition-colors">
                      <TableCell className="py-2.5">
                        <div className="font-semibold text-[13px] text-foreground">
                          {p.display_name || p.slug}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                          {p.slug}
                        </div>
                      </TableCell>
                      <TableCell className="py-2.5">
                        {p.adapter ? (
                          <Badge
                            variant="outline"
                            className="bg-muted/20 font-mono text-[10px] font-medium text-foreground"
                          >
                            {p.adapter}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground/60">—</span>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[180px] py-2.5">
                        {p.base_url ? (
                          <div
                            className="flex items-center gap-1.5 truncate font-mono text-xs text-muted-foreground"
                            title={p.base_url}
                          >
                            <Link2 className="h-3 w-3 shrink-0" />
                            <span className="truncate">{p.base_url}</span>
                          </div>
                        ) : (
                          <Badge
                            variant="outline"
                            className="border-dashed font-mono text-[10px] text-muted-foreground/70"
                          >
                            default endpoint
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="py-2.5">
                        {p.key_env ? (
                          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                            {p.key_env}
                          </code>
                        ) : (
                          <span className="text-muted-foreground/60">—</span>
                        )}
                      </TableCell>
                      <TableCell className="py-2.5">
                        <Badge
                          variant="outline"
                          className={
                            p.tier === "free"
                              ? "border-blue-500/20 bg-blue-500/10 text-[10px] text-blue-600 dark:text-blue-400"
                              : "border-amber-500/20 bg-amber-500/10 text-[10px] text-amber-600 dark:text-amber-400"
                          }
                        >
                          {p.tier}
                        </Badge>
                      </TableCell>
                      <TableCell className="py-2.5">
                        <div className="flex flex-wrap gap-1.5">
                          {p.enabled ? (
                            <Badge
                              variant="outline"
                              className="h-5 gap-1.5 border-emerald-500/20 bg-emerald-500/10 px-1.5 text-[10px] text-emerald-600 dark:text-emerald-400"
                            >
                              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                              Enabled
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="h-5 gap-1.5 border-border bg-muted px-1.5 text-[10px] text-muted-foreground"
                            >
                              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                              Disabled
                            </Badge>
                          )}
                          {p.status === "deprecated" && (
                            <Badge
                              variant="outline"
                              className="h-5 border-rose-500/20 bg-rose-500/10 px-1.5 text-[10px] text-rose-600 dark:text-rose-400"
                            >
                              Deprecated
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => toggle(p)}
                            className="h-7 px-2 text-[11px]"
                          >
                            <Power className="mr-1 h-3 w-3" />
                            {p.enabled ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setEditing(p)}
                            className="h-7 px-2 text-[11px]"
                          >
                            <Edit3 className="mr-1 h-3 w-3" />
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => remove(p)}
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
          </Card>

          <div className="mt-3 flex shrink-0 items-start gap-2.5 rounded-lg border border-border/50 bg-muted/20 p-2.5 text-[11px] text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
            <p className="leading-relaxed">
              Disabled providers (and their models) disappear from the customer
              dashboard immediately — running calls are unaffected.
            </p>
          </div>
        </StateBox>
      </div>

      {showCreate && (
        <ProviderFormModal
          provider={null}
          defaultKind={kind}
          onClose={() => setShowCreate(false)}
          onSaved={() => refetch()}
        />
      )}
      {editing && ( 
        <ProviderFormModal
          provider={editing}
          defaultKind={kind}
          onClose={() => setEditing(null)}
          onSaved={() => refetch()}
        />
      )}
    </div>
  );
}