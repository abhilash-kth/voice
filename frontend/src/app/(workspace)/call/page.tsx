"use client";

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PhoneCall, RefreshCw } from "lucide-react";
import { listAgents } from "@/lib/index";
import CallPanel from "@/app/(workspace)/call/components/CallPanel";
import { Button } from "@/components/ui/button";

export default function CallPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const presetAgentId = searchParams.get("preset") || "";

  const { data, isPending, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
  });

  const agents = data?.agents ?? [];
  const agentsReady = !isPending && !isError;

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <PhoneCall className="h-4 w-4" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              Live Call
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Pick an agent and start a real-time voice session in the browser.
          </p>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 shrink-0 gap-2"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
          />
          {isFetching ? "Refreshing..." : "Refresh agents"}
        </Button>
      </div>

      {isError && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
          {(error as Error)?.message ||
            "Could not load agents. Check that the backend is running."}
        </div>
      )}

      <CallPanel
        agents={agents}
        onStarted={() => {
          void refetch();
        }}
        presetAgentId={presetAgentId}
        onPresetConsumed={() => {
          router.replace(pathname, { scroll: false });
        }}
        agentsReady={agentsReady}
      />
    </div>
  );
}
