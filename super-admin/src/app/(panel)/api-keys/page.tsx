"use client";

import { useState } from "react";
import {
  Plus,
  KeyRound,
  RefreshCw,
  Power,
  CheckCircle2,
  XCircle,
  Info,
  Cpu,
  Mic,
  Volume2,
  PhoneCall,
  Layers,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import PageHeader, { useBusy } from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import CredentialFormModal from "@/components/CredentialFormModal";
import {
  listCredentials,
  setCredentialStatus,
  listProviders,
  type Credential,
  type Provider,
} from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
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

const KIND_FILTERS = ["", "llm", "stt", "tts", "telephony"] as const;

const KIND_ICONS: Record<string, React.ElementType> = {
  "": Layers,
  llm: Cpu,
  stt: Mic,
  tts: Volume2,
  telephony: PhoneCall,
};

export default function ApiKeysPage() {
  const [kindFilter, setKindFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [rotating, setRotating] = useState<Credential | null>(null);
  const { busy, msg, err, run } = useBusy();

  const {
    data: items = [],
    isPending: loading,
    error,
    refetch,
  } = useQuery<Credential[], Error>({
    queryKey: ["credentials", { kind: kindFilter }],
    queryFn: async () => {
      const r = await listCredentials(kindFilter ? { kind: kindFilter } : {});
      return r.items;
    },
  });

  const { data: providers = [] } = useQuery<Provider[], Error>({
    queryKey: ["providers", "all"],
    queryFn: async () => {
      const r = await listProviders();
      return r.items;
    },
  });

  const setStatus = (c: Credential, status: "active" | "disabled") =>
    run(
      () => setCredentialStatus(c.id, status),
      status === "active"
        ? "Key re-enabled ✓"
        : "Key disabled — falls back to env var if set",
    ).then((ok) => {
      if (ok !== undefined) refetch();
    });

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="shrink-0">
        <PageHeader
          title="API Keys"
          subtitle="Provider credentials — encrypted at rest, write-only, always shown masked"
        >
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Add key
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
              ? "No keys stored. Calls fall back to the provider's env-var key (if set)."
              : null
          }
        >
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden border border-border/60 shadow-sm py-0">
            {/* Kind filter toolbar */}
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-card px-4 py-2.5">
              <div className="inline-flex rounded-lg border border-border/60 bg-muted/40 p-1">
                {KIND_FILTERS.map((k) => {
                  const Icon = KIND_ICONS[k] || Layers;
                  const active = kindFilter === k;
                  return (
                    <button
                      key={k || "all"}
                      type="button"
                      onClick={() => setKindFilter(k)}
                      className={`flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-semibold uppercase tracking-wider transition-all ${
                        active
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Icon className="h-3 w-3" />
                      <span>{k === "" ? "All" : k}</span>
                    </button>
                  );
                })}
              </div>

              <div className="text-[11px] tabular-nums text-muted-foreground">
                <span className="font-semibold text-foreground">
                  {items.length}
                </span>{" "}
                {items.length === 1 ? "key" : "keys"}
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
                      Label
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Key (masked)
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Status
                    </TableHead>
                    <TableHead className="py-2.5 text-xs font-semibold">
                      Updated
                    </TableHead>
                    <TableHead className="py-2.5 text-right text-xs font-semibold">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((c) => (
                    <TableRow key={c.id} className="transition-colors">
                      <TableCell className="py-2.5">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                            <KeyRound className="h-3.5 w-3.5" />
                          </div>
                          <div className="min-w-0">
                            <div className="font-semibold text-[13px] text-foreground">
                              {c.provider_slug}
                            </div>
                            <div className="text-[11px] font-mono uppercase text-muted-foreground">
                              {c.kind}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="py-2.5 text-[13px] text-foreground">
                        {c.label || (
                          <span className="text-muted-foreground/60">—</span>
                        )}
                      </TableCell>
                      <TableCell className="py-2.5">
                        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                          {c.masked_value}
                        </code>
                      </TableCell>
                      <TableCell className="py-2.5">
                        {c.status === "active" ? (
                          <Badge
                            variant="outline"
                            className="h-5 gap-1.5 border-emerald-500/20 bg-emerald-500/10 px-1.5 text-[10px] text-emerald-600 dark:text-emerald-400"
                          >
                            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                            active
                          </Badge>
                        ) : c.status === "rotated" ? (
                          <Badge
                            variant="outline"
                            className="h-5 gap-1.5 border-amber-500/20 bg-amber-500/10 px-1.5 text-[10px] text-amber-600 dark:text-amber-400"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                            rotated
                          </Badge>
                        ) : (
                          <Badge
                            variant="outline"
                            className="h-5 gap-1.5 border-border bg-muted px-1.5 text-[10px] text-muted-foreground"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                            {c.status || "disabled"}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="py-2.5 text-xs tabular-nums text-muted-foreground">
                        {fmtDateTime(c.updated_at)}
                      </TableCell>
                      <TableCell className="py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 px-2 text-[11px]"
                            onClick={() => setRotating(c)}
                          >
                            <RefreshCw className="mr-1 h-3 w-3" />
                            Rotate
                          </Button>
                          {c.status === "active" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-[11px] text-destructive hover:bg-destructive/10 hover:text-destructive"
                              disabled={busy}
                              onClick={() => setStatus(c, "disabled")}
                            >
                              <Power className="mr-1 h-3 w-3" />
                              Disable
                            </Button>
                          ) : c.status === "disabled" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-[11px]"
                              disabled={busy}
                              onClick={() => setStatus(c, "active")}
                            >
                              <Power className="mr-1 h-3 w-3" />
                              Enable
                            </Button>
                          ) : null}
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
              Plaintext keys are never stored readable and never leave the
              server in any response. Rotated keys are kept (masked) for audit.
            </p>
          </div>
        </StateBox>
      </div>

      {showCreate && (
        <CredentialFormModal
          mode="create"
          providers={providers}
          onClose={() => setShowCreate(false)}
          onSaved={() => refetch()}
        />
      )}
      {rotating && (
        <CredentialFormModal
          mode="rotate"
          credential={rotating}
          providers={providers}
          onClose={() => setRotating(null)}
          onSaved={() => refetch()}
        />
      )}
    </div>
  );
}
