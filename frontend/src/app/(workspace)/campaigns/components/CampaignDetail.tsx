"use client";

import { useState } from "react";
import {
  PhoneCall,
  Users,
  Check,
  Clock3,
  CircleAlert,
  Pause,
  Play,
  Trash2,
  Megaphone,
} from "lucide-react";
import {
  Campaign,
  CampaignLead,
  deleteCampaign,
  getCampaign,
  pauseCampaign,
  startCampaign,
} from "@/lib/campaigns";
import { Button } from "@/components/ui/button";
import CampaignStatusBadge, { CampaignProgress } from "./CampaignStatusBadge";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export default function CampaignDetail({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState("");
  const {
    data: campaign,
    error: queryError,
    isPending,
  } = useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => getCampaign(campaignId),
    refetchInterval: 2500,
    refetchIntervalInBackground: true,
  });
  const actionMutation = useMutation({
    mutationFn: (action: "start" | "pause") =>
      action === "start"
        ? startCampaign(campaignId)
        : pauseCampaign(campaignId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["campaign", campaignId] }),
        queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
      ]);
    },
  });
  
  const deleteMutation = useMutation({
    mutationFn: () => deleteCampaign(campaignId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      router.push("/campaigns");
    },
  });

  const act = async (action: "start" | "pause") => {
    setActionError("");
    try {
      await actionMutation.mutateAsync(action);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete this campaign and its lead list?")) return;
    setActionError("");
    try {
      await deleteMutation.mutateAsync();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  if (!campaign)
    return (
      <div className="w-full space-y-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Megaphone className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
              Campaign details
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Loading campaign information…
            </p>
          </div>
        </div>
        {queryError ? (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            {(queryError as Error).message}
          </p>
        ) : isPending ? (
          <div className="rounded-xl border border-border bg-card p-8 text-sm text-muted-foreground">
            Loading campaign…
          </div>
        ) : null}
      </div>
    );

  const total = campaign.summary.total;
  const pct = total
    ? Math.round(
        ((campaign.summary.done + campaign.summary.failed) / total) * 100,
      )
    : 0;
  const stats = [
    {
      label: "Completed",
      value: campaign.summary.done,
      icon: Check,
      tone: "text-emerald-600 dark:text-emerald-400",
    },
    {
      label: "In progress",
      value: campaign.summary.calling,
      icon: PhoneCall,
      tone: "text-amber-600 dark:text-amber-400",
    },
    {
      label: "Waiting",
      value: campaign.summary.queued,
      icon: Clock3,
      tone: "text-foreground",
    },
    {
      label: "Failed",
      value: campaign.summary.failed,
      icon: CircleAlert,
      tone: "text-rose-600 dark:text-rose-400",
    },
  ];

  return (
    <div className="w-full space-y-6">
      {(actionError || (!campaign && queryError)) && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {actionError || (queryError as Error).message}
        </p>
      )}
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Megaphone className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="break-words text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                {campaign.name}
              </h2>
              <CampaignStatusBadge status={campaign.status} />
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Created {new Date(campaign.created_at).toLocaleString()}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={actionMutation.isPending || deleteMutation.isPending}
            variant={campaign.status === "running" ? "secondary" : "default"}
            onClick={() =>
              void act(campaign.status === "running" ? "pause" : "start")
            }
          >
            {campaign.status === "running" ? (
              <>
                <Pause className="mr-2 size-4" /> Pause campaign
              </>
            ) : (
              <>
                <Play className="mr-2 size-4" />{" "}
                {campaign.status === "done" ? "Run again" : "Start campaign"}
              </>
            )}
          </Button>
          <Button
            disabled={actionMutation.isPending || deleteMutation.isPending}
            variant="outline"
            onClick={() => void remove()}
          >
            <Trash2 className="mr-2 size-4" /> Delete
          </Button>
        </div>
      </header>
      <section className="rounded-xl border border-border bg-card p-4 text-card-foreground shadow-sm sm:p-5">
        <div>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                Campaign progress
              </h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Live results for this lead list.
              </p>
            </div>
            <span className="text-sm font-semibold tabular-nums">{pct}%</span>
          </div>
        </div>
        <div className="mt-3">
          <CampaignProgress value={pct} />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {campaign.summary.done + campaign.summary.failed} of {total} leads
          processed · {campaign.concurrency} concurrent calls
          {campaign.phone_column
            ? " · Phone column: " + campaign.phone_column
            : ""}
        </p>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {stats.map(({ label, value, icon: Icon, tone }) => (
            <div
              key={label}
              className="rounded-xl border bg-background/60 p-3.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Icon className={"size-4 " + tone} />
              </div>
              <p className={"mt-2 text-xl font-semibold " + tone}>{value}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5 sm:px-5">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
              Lead activity
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Live status for each contact in this campaign.
            </p>
          </div>
          <span className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
            {campaign.leads?.length ?? 0} leads
          </span>
        </div>
        <LeadTable
          leads={campaign.leads || []}
          phoneColumn={campaign.phone_column}
        />
      </section>
    </div>
  );
}

function LeadTable({
  leads,
  phoneColumn,
}: {
  leads: CampaignLead[];
  phoneColumn: string;
}) {
  const headers = leads.length ? Object.keys(leads[0].data || {}) : [];
  const extraHeaders = headers
    .filter((header) => header !== phoneColumn)
    .slice(0, 4);
  return (
    <div className="max-h-[560px] overflow-auto">
      <table className="w-full min-w-[680px] text-left text-sm">
        <thead className="sticky top-0 z-10 bg-muted/90 text-xs text-muted-foreground backdrop-blur">
          <tr>
            <th className="px-5 py-3 font-medium">#</th>
            <th className="px-4 py-3 font-medium">Phone</th>
            {extraHeaders.map((header) => (
              <th key={header} className="px-4 py-3 font-medium">
                {header}
              </th>
            ))}
            <th className="px-5 py-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {leads.map((lead) => (
            <tr
              key={lead.index}
              className="transition-colors hover:bg-muted/40"
            >
              <td className="px-5 py-3 text-xs text-muted-foreground">
                {lead.index}
              </td>
              <td className="px-4 py-3 font-mono text-xs">
                {lead.data?.[phoneColumn] ?? ""}
              </td>
              {extraHeaders.map((header) => (
                <td
                  key={header}
                  className="max-w-48 truncate px-4 py-3 text-muted-foreground"
                >
                  {lead.data?.[header] ?? ""}
                </td>
              ))}
              <td className="px-5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <CampaignStatusBadge status={lead.status} />
                  {lead.error && (
                    <span
                      title={lead.error}
                      className="max-w-48 truncate text-xs text-destructive"
                    >
                      {lead.error}
                    </span>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {leads.length === 0 && (
            <tr>
              <td
                colSpan={extraHeaders.length + 3}
                className="px-5 py-12 text-center text-sm text-muted-foreground"
              >
                No lead details available yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
