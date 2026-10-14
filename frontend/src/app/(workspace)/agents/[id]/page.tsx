"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Bot,
  Pencil,
  Plus,
  Settings2,
  AudioLines,
  Shield,
} from "lucide-react";
import { Agent, Catalog, getCatalog, listAgents } from "@/lib/index";
import AgentConfigForm from "@/app/(workspace)/agents/components/AgentConfigForm";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { LoadingGrid } from "@/components/LoadingGrid";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

/**
 * Pure split of the form half of the original AgentsPage.
 * - Same catalog + agents fetch (Promise.all)
 * - Same queryKey family
 * - Same AgentConfigForm props: catalog, editing, onDone
 * - editing is null for /agents/new (same as setEditing(null))
 * - editing is the matched agent for /agents/:id (same as setEditing(a))
 * - onDone: notice was parent-only; here we navigate back after same delay pattern optional
 */
export default function AgentFormPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const router = useRouter();
  const { id } = use(params);
  const isNew = id === "new";

  const backendError =
    "Could not reach the backend at localhost:8000. Start it with: uvicorn app.main:app --port 8000";

  // SAME fetch as original page — do not change
  const {
    data,
    isPending,
    error,
    refetch: refetchCatalogAgents,
  } = useQuery({
    queryKey: ["catalogs", "agents"],
    queryFn: async () => {
      const [c, a] = await Promise.all([getCatalog(), listAgents()]);
      return {
        c,
        agents: a.agents,
      };
    },
  });

  if (isPending || error) {
    return (
      <LoadingGrid
        loading={isPending}
        error={error instanceof Error ? error.message : backendError}
      />
    );
  }

  const catalog: Catalog = data.c;
  const agents: Agent[] = data?.agents ?? [];

  // Same as setEditing(null) vs setEditing(a)
  const editing: Agent | null = isNew
    ? null
    : (agents.find((a) => a.id === id) ?? null);

  // Edit URL but agent missing from list
  if (!isNew && !editing) {
    return (
      <div className="flex w-full flex-col gap-6">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-9 w-9"
            onClick={() => router.push("/agents")}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Agent not found
          </h1>
        </div>
        <div className="flex w-full flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-20 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
            <Bot className="h-7 w-7" />
          </div>
          <p className="text-sm font-semibold text-foreground">
            This agent doesn’t exist
          </p>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            It may have been deleted, or the link is invalid.
          </p>
          <Button
            type="button"
            className="mt-6 h-9 gap-2"
            onClick={() => router.push("/agents")}
          >
            <ArrowLeft className="h-4 w-4" />
            Back to agents
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col gap-8">
      {/* ── Full-width dashboard header ── */}
      <header className="w-full space-y-5">
        {/* Back + breadcrumb */}
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="-ml-2 h-8 gap-1.5 px-2 text-muted-foreground hover:text-foreground"
            onClick={() => router.push("/agents")}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Agents
          </Button>
          <span className="text-border">/</span>
          <span className="font-medium text-foreground">
            {editing ? editing.name : "New agent"}
          </span>
        </div>

        {/* Title row */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-start gap-4">
            <div
              className={cn(
                "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl shadow-sm",
                editing
                  ? "bg-primary text-primary-foreground"
                  : "bg-emerald-600 text-white dark:bg-emerald-500",
              )}
            >
              {editing ? (
                <Pencil className="h-6 w-6" />
              ) : (
                <Plus className="h-6 w-6" />
              )}
            </div>
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                  {editing ? editing.name : "Create agent"}
                </h1>
                <Badge
                  className={cn(
                    "h-6 border-0 px-2 text-[11px] font-semibold uppercase tracking-wide",
                    editing
                      ? "bg-primary/15 text-primary hover:bg-primary/15"
                      : "bg-emerald-500/15 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-400",
                  )}
                >
                  {editing ? "Editing" : "New"}
                </Badge>
                {editing && (
                  <>
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-6 px-2 text-[11px] font-semibold capitalize",
                        editing.agent_mode === "announcement"
                          ? "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400"
                          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                      )}
                    >
                      {editing.agent_mode === "announcement"
                        ? "Announcement"
                        : "Assistant"}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-6 px-2 text-[11px] font-semibold uppercase",
                        editing.enabled
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                          : "border-border bg-muted text-muted-foreground",
                      )}
                    >
                      {editing.enabled ? "Active" : "Off"}
                    </Badge>
                  </>
                )}
              </div>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                {editing
                  ? "Update LLM, STT, TTS, prompts, memory, recording, and concurrency. Changes apply on the next call."
                  : "Define how this agent sounds and thinks — providers, language, system prompt, and runtime limits."}
              </p>
            </div>
          </div>

          <Button
            type="button"
            variant="outline"
            className="h-9 shrink-0 gap-2 bg-card"
            onClick={() => router.push("/agents")}
          >
            Cancel
          </Button>
        </div>

        {/* Context strip */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/10 text-violet-600 dark:text-violet-400">
              <Settings2 className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Configuration
              </p>
              <p className="truncate text-sm font-medium text-foreground">
                Providers & models
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-500/10 text-sky-600 dark:text-sky-400">
              <AudioLines className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Voice
              </p>
              <p className="truncate text-sm font-medium text-foreground">
                STT · TTS · language
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <Shield className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Runtime
              </p>
              <p className="truncate text-sm font-medium text-foreground">
                Memory · recording · limits
              </p>
            </div>
          </div>
        </div>
      </header>

      <Separator className="bg-border" />

      {/* ── Full-width form workspace ── */}
      {catalog && (
        <section className="w-full space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                Agent configuration
              </h2>
              <p className="text-xs text-muted-foreground">
                {editing
                  ? `Editing “${editing.name}”`
                  : "Complete the fields below, then save to create the agent"}
              </p>
            </div>
            <Badge
              variant="outline"
              className="hidden h-6 gap-1 border-border bg-card px-2 text-[10px] text-muted-foreground sm:inline-flex"
            >
              <Bot className="h-3 w-3" />
              Workspace
            </Badge>
          </div>

          {/* Solid full-width surface — not a narrow nested card */}
          <div className="w-full rounded-xl border border-border bg-card p-5 shadow-sm sm:p-8">
            <AgentConfigForm
              key={editing?.id ?? "new"}
              catalog={catalog}
              editing={editing}
              onDone={(m) => {
                toast.success(m);
                refetchCatalogAgents();
                setTimeout(() => router.push("/agents"), 600);
              }}
            />
          </div>
        </section>
      )}
    </div>
  );
}
