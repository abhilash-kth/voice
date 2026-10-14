import { CampaignLead } from "@/lib/campaigns";

const styles: Record<string, string> = {
  running: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  paused: "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  done: "border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  failed: "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  calling: "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  queued: "border-border bg-muted text-muted-foreground",
};

export default function CampaignStatusBadge({ status }: { status: string }) {
  return (
    <span className={"inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium capitalize " + (styles[status] || styles.queued)}>
      {status === "running" && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {status}
    </span>
  );
}

export function CampaignProgress({ value }: { value: number }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: value + "%" }} />
    </div>
  );
}

export type CampaignLeadStatus = CampaignLead["status"];
