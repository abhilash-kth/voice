"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Megaphone,
  Pause,
  Play,
  Plus,
  Trash2,
  Users,
  PhoneCall,
} from "lucide-react";
import {
  Campaign,
  deleteCampaign,
  listCampaigns,
  pauseCampaign,
  startCampaign,
} from "@/lib/campaigns";
import { Button, buttonVariants } from "@/components/ui/button";
import CampaignStatusBadge, { CampaignProgress } from "./CampaignStatusBadge";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export default function CampaignList() {
  const [busyId, setBusyId] = useState("");
  const queryClient = useQueryClient();
  const { data, error, isPending } = useQuery({
    queryKey: ["campaigns"],
    queryFn: async () => {
      const result = await listCampaigns();
      return result.campaigns;
    },
  });

  const campaigns: Campaign[] = data || [];

  const refreshCampaigns = () =>
    queryClient.invalidateQueries({ queryKey: ["campaigns"] });

  const actionMutation = useMutation({
    mutationFn: async ({
      id,
      action,
    }: {
      id: string;
      action: "start" | "pause";
    }) => {
      if (action === "start") return startCampaign(id);
      return pauseCampaign(id);
    },
    onSuccess: refreshCampaigns,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCampaign,
    onSuccess: refreshCampaigns,
  });

  const act = async (id: string, action: "start" | "pause") => {
    setBusyId(id);
    try {
      await actionMutation.mutateAsync({ id, action });
    } catch (e) {
      toast.error((e as Error).message || "Something went wrong");
    } finally {
      setBusyId("");
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this campaign and its lead list?")) return;
    setBusyId(id);
    try {
      await deleteMutation.mutateAsync(id);
    } catch (e) {
      toast.error((e as Error).message || "Could not delete campaign");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="w-full space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Megaphone className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
              Campaigns
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Create and monitor your lead outreach campaigns.
            </p>
          </div>
        </div>
        <Link
          href="/campaigns/new"
          className={buttonVariants({
            className: "h-9 w-full gap-2 sm:w-auto",
          })}
        >
          <Plus className="h-4 w-4" /> New campaign
        </Link>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {(error as Error).message || "Could not load campaigns."}
        </p>
      )}
      {isPending ? (
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          Loading campaigns…
        </div>
      ) : error ? null : campaigns.length === 0 ? (
        <section className="rounded-xl border border-dashed border-border bg-card px-6 py-16 text-center">
          <div className="mx-auto grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
            <Megaphone className="size-5" />
          </div>
          <h2 className="mt-4 font-semibold">No campaigns yet</h2>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
            Create a campaign and upload your lead list to get started.
          </p>
          <Link
            href="/campaigns/new"
            className={buttonVariants({ className: "mt-5" })}
          >
            <Plus className="mr-2 size-4" /> Create campaign
          </Link>
        </section>
      ) : (
        <section className="grid gap-4 xl:grid-cols-2">
          {campaigns.map((campaign) => {
            const total = campaign.summary.total;
            const pct = total
              ? Math.round(
                  ((campaign.summary.done + campaign.summary.failed) / total) *
                    100,
                )
              : 0;
            return (
              <article
                key={campaign.id}
                className="rounded-xl border border-border bg-card p-4 text-card-foreground shadow-sm transition-colors hover:border-primary/30 hover:bg-accent/30 sm:p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                      <Megaphone className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <h2 className="truncate font-semibold">
                        {campaign.name}
                      </h2>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Created{" "}
                        {new Date(campaign.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <CampaignStatusBadge status={campaign.status} />
                </div>
                <div className="mt-6 flex items-center justify-between text-xs text-muted-foreground">
                  <span>Lead progress</span>
                  <span>{pct}%</span>
                </div>
                <div className="mt-2">
                  <CampaignProgress value={pct} />
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    [
                      "Done",
                      campaign.summary.done,
                      "text-emerald-600 dark:text-emerald-400",
                    ],
                    [
                      "Calling",
                      campaign.summary.calling,
                      "text-amber-600 dark:text-amber-400",
                    ],
                    ["Queued", campaign.summary.queued, "text-foreground"],
                    [
                      "Failed",
                      campaign.summary.failed,
                      "text-rose-600 dark:text-rose-400",
                    ],
                  ].map(([label, value, color]) => (
                    <div
                      key={String(label)}
                      className="rounded-xl bg-muted/60 px-3 py-2.5"
                    >
                      <div className={"text-lg font-semibold " + color}>
                        {value}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1">
                    <Users className="size-3.5" /> {total} leads
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1">
                    <PhoneCall className="size-3.5" /> {campaign.concurrency}{" "}
                    concurrent calls
                  </span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={
                      campaign.status === "running" ? "secondary" : "default"
                    }
                    disabled={busyId === campaign.id}
                    onClick={() =>
                      void act(
                        campaign.id,
                        campaign.status === "running" ? "pause" : "start",
                      )
                    }
                  >
                    {campaign.status === "running" ? (
                      <>
                        <Pause className="mr-1.5 size-3.5" /> Pause
                      </>
                    ) : (
                      <>
                        <Play className="mr-1.5 size-3.5" />{" "}
                        {campaign.status === "done" ? "Re-run" : "Start"}
                      </>
                    )}
                  </Button>
                  <Link
                    href={"/campaigns/" + campaign.id}
                    className={buttonVariants({
                      size: "sm",
                      variant: "outline",
                    })}
                  >
                    View details <ArrowUpRight className="ml-1.5 size-3.5" />
                  </Link>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto text-muted-foreground hover:text-destructive"
                    disabled={busyId === campaign.id}
                    onClick={() => void remove(campaign.id)}
                  >
                    <Trash2 className="mr-1.5 size-3.5" /> Delete
                  </Button>
                </div>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
