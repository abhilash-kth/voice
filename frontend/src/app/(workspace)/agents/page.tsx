"use client";

import { useRouter } from "next/navigation";
import {
  Bot,
  Plus,
  Pencil,
  PhoneCall,
  Trash2,
  Brain,
  Mic,
  Volume2,
  MemoryStick,
  CircleDot,
  Layers,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Agent, getCatalog, listAgents, deleteAgent } from "@/lib/index";
import { useQuery } from "@tanstack/react-query";
import { LoadingGrid } from "@/components/LoadingGrid";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export default function AgentsPage() {
  const router = useRouter();
  const backendError =
    "Could not reach the backend at localhost:8000. Start it with: uvicorn app.main:app --port 8000";

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

  const agents: Agent[] = data?.agents ?? [];

  const removeAgent = async (a: Agent) => {
    const ok = window.confirm(
      `Delete agent "${a.name}"? All of its call history will also be removed.`,
    );
    if (!ok) return;
    try {
      await deleteAgent(a.id);
      toast.success(`Deleted ${a.name}`);
      refetchCatalogAgents();
    } catch (e) {
      toast.error(`Could not delete: ${(e as Error).message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
              Agents
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Create and configure voice agents, then assign them to calls.
            </p>
          </div>
        </div>
        <Button
          type="button"
          className="h-9 w-full gap-2 sm:w-auto"
          onClick={() => router.push("/agents/new")}
        >
          <Plus className="h-4 w-4" />
          New agent
        </Button>
      </div>

      {agents.length === 0 && (
        <div className="flex w-full flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-16 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
            <Bot className="h-7 w-7" />
          </div>
          <p className="text-sm font-semibold text-foreground">No agents yet</p>
          <p className="mt-1.5 max-w-[320px] text-xs leading-relaxed text-muted-foreground">
            Create an agent — pick a provider, language and voice — and it will
            be ready to take calls in seconds.
          </p>
        </div>
      )}

      {agents.length > 0 && (
        <div className="flex w-full flex-col gap-3">
          {agents.map((a) => {
            const isAnnouncement = a.agent_mode === "announcement";
            const isLive = (a.active_calls ?? 0) > 0;

            return (
              <div
                key={a.id}
                className={cn(
                  "group w-full overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm transition-colors",
                  "hover:border-primary/30 hover:bg-accent/30",
                )}
              >
                <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:gap-5 sm:p-5">
                  <div className="flex min-w-0 flex-1 items-start gap-3 sm:items-center">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-base font-semibold tracking-tight text-foreground">
                          {a.name}
                        </h3>

                        <Badge
                          variant="outline"
                          className={cn(
                            "h-5 gap-1 px-1.5 text-[10px] font-semibold uppercase tracking-wider",
                            a.enabled
                              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                              : "border-border bg-muted text-muted-foreground",
                          )}
                        >
                          {a.enabled ? (
                            <span className="relative flex h-1.5 w-1.5">
                              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            </span>
                          ) : null}
                          {a.enabled ? "Active" : "Off"}
                        </Badge>

                        <Badge
                          variant="outline"
                          className={cn(
                            "h-5 px-1.5 text-[10px] font-semibold capitalize",
                            isAnnouncement
                              ? "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400"
                              : "border-primary/25 bg-primary/10 text-primary",
                          )}
                        >
                          {isAnnouncement ? "Announcement" : "Assistant"}
                        </Badge>

                        {isLive && (
                          <Badge
                            variant="outline"
                            className="h-5 gap-1 border-amber-500/30 bg-amber-500/10 px-1.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400"
                          >
                            <span className="relative flex h-1.5 w-1.5">
                              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-70" />
                              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                            </span>
                            {a.active_calls} live
                          </Badge>
                        )}
                      </div>

                      <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
                        {a.description || "No description"}
                      </p>

                      <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        <MetaChip
                          icon={Brain}
                          text={a.providers.llm.id}
                          className="border-violet-500/20 bg-violet-500/10 text-violet-700 dark:text-violet-400"
                        />
                        <MetaChip
                          icon={Mic}
                          text={a.providers.stt.id}
                          className="border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-400"
                        />
                        <MetaChip
                          icon={Volume2}
                          text={a.providers.tts.id}
                          className="border-teal-500/20 bg-teal-500/10 text-teal-700 dark:text-teal-400"
                        />
                        <span className="mx-0.5 hidden h-4 w-px bg-border sm:inline-block" />
                        <MetaChip
                          icon={MemoryStick}
                          text={a.memory_enabled ? "Memory" : "No memory"}
                          className={
                            a.memory_enabled
                              ? "border-violet-500/20 bg-violet-500/10 text-violet-700 dark:text-violet-400"
                              : "border-border bg-muted text-muted-foreground"
                          }
                        />
                        <MetaChip
                          icon={CircleDot}
                          text={a.recording_enabled ? "Recording" : "No rec"}
                          className={
                            a.recording_enabled
                              ? "border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-400"
                              : "border-border bg-muted text-muted-foreground"
                          }
                        />
                        <MetaChip
                          icon={Layers}
                          text={`×${a.max_concurrency}`}
                          className="border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-400"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-3 border-t border-border pt-3 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
                    <div className="flex items-center gap-4 sm:justify-end">
                      <div className="text-left sm:text-right">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Calls
                        </p>
                        <p className="text-sm font-bold tabular-nums text-foreground">
                          {a.call_count ?? 0}
                          <span className="ml-1 text-xs font-medium text-muted-foreground">
                            · {a.active_calls ?? 0} live
                          </span>
                        </p>
                      </div>
                      <div className="text-left sm:text-right">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Billed
                        </p>
                        <p className="text-sm font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                          ₹{a.total_billed ?? 0}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 sm:justify-end">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="h-8 gap-1.5 bg-background text-xs"
                        onClick={() => router.push(`/agents/${a.id}`)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-8 gap-1.5 bg-green-400 text-xs text-black hover:bg-green-500"
                        onClick={() => {
                          router.push(`/dashboard/call?preset=${a.id}`);
                        }}
                      >
                        <PhoneCall className="h-3.5 w-3.5" />
                        Call
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        className="h-8 gap-1.5"
                        onClick={() => removeAgent(a)}
                        title="Delete this agent"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetaChip({
  icon: Icon,
  text,
  className,
}: {
  icon: React.ElementType;
  text: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-[160px] items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium",
        className,
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="truncate font-mono">{text}</span>
    </span>
  );
}
