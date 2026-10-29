"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FileSpreadsheet,
  Megaphone,
  Upload,
  Users,
  CircleHelp,
} from "lucide-react";
import { Agent } from "@/lib";
import { createCampaign } from "@/lib/campaigns";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

export default function CreateCampaignForm({
  agents,
  onChanged,
}: {
  agents: Agent[];
  onChanged?: () => void;
}) {
  const router = useRouter();
  const eligibleAgents = agents.filter((agent) =>
    ["outbound", "both"].includes(agent.purpose || "outbound"),
  );
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [concurrency, setConcurrency] = useState(5);
  const [sipTrunkId, setSipTrunkId] = useState("");
  const [phoneColumn, setPhoneColumn] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (agentId && !eligibleAgents.some((agent) => agent.id === agentId)) {
      setAgentId("");
    } else if (!agentId && eligibleAgents.length) {
      setAgentId(eligibleAgents[0].id);
    }
  }, [eligibleAgents, agentId]);
  const selectedAgent = eligibleAgents.find((agent) => agent.id === agentId);

  const submit = async () => {
    if (!agentId) {
      toast.error("Select an agent first.");
      return;
    }
    if (!file) {
      toast.error("Upload a .csv or .xlsx lead file.");
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.set("name", name || "Campaign");
      form.set("agent_id", agentId);
      form.set("concurrency", String(concurrency || 1));
      // Assigned purchased numbers use their backend-managed trunk.
      if (sipTrunkId && !selectedAgent?.phone_number_id) {
        form.set("sip_trunk_id", sipTrunkId);
      }
      if (phoneColumn) form.set("phone_column", phoneColumn);
      form.set("autostart", "true");
      form.set("file", file);
      const campaign = await createCampaign(form);
      setFile(null);
      setName("");
      onChanged?.();
      router.push("/campaigns/" + campaign.id);
    } catch (e) {
      toast.error((e as Error).message || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full space-y-6">
      <header className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Megaphone className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
            Create a campaign
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Choose an agent, upload leads, and configure call delivery.
          </p>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm">
        <div className="border-b border-border px-4 py-3.5 sm:px-5">
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Campaign details
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            This campaign starts automatically after it is created.
          </p>
        </div>
        <div className="space-y-6 p-5 sm:p-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="space-y-2 text-sm font-medium sm:col-span-2">
              Campaign name
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. October renewal reminders"
              />
            </label>
            <label className="space-y-2 text-sm font-medium sm:col-span-2">
              Calling agent
              <select
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                {eligibleAgents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name} — {agent.purpose || "outbound"}
                    {agent.phone_number ? ` · ${agent.phone_number}` : ""}
                  </option>
                ))}
              </select>
              <span className="block text-xs font-normal text-muted-foreground">
                {eligibleAgents.length === 0
                  ? "No outbound or both-purpose agents are available. Create one before starting a campaign."
                  : selectedAgent?.phone_number
                    ? `Calls will show caller ID ${selectedAgent.phone_number}; its trunk is managed automatically.`
                    : "Inbound-only agents are hidden because campaigns place outbound calls."}
              </span>
            </label>
            <label className="space-y-2 text-sm font-medium">
              Concurrent calls
              <Input
                type="number"
                min={1}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
              />
              <span className="block text-xs font-normal text-muted-foreground">
                Maximum calls placed at the same time.
              </span>
            </label>
            {selectedAgent?.phone_number_id ? (
              <div className="space-y-2 text-sm font-medium">
                SIP trunk
                <div className="flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm font-normal text-muted-foreground">
                  Managed from assigned number
                </div>
              </div>
            ) : (
              <label className="space-y-2 text-sm font-medium">
                SIP trunk ID{" "}
                <span className="font-normal text-muted-foreground">
                  (optional)
                </span>
                <Input
                  value={sipTrunkId}
                  onChange={(e) => setSipTrunkId(e.target.value)}
                  placeholder="Default or ST_xxxx"
                />
              </label>
            )}
          </div>

          <div className="space-y-2">
            <div>
              <h3 className="text-sm font-medium">Lead list</h3>
              <p className="text-xs text-muted-foreground">
                Upload a spreadsheet with one contact per row.
              </p>
            </div>
            <label
              className={
                "flex cursor-pointer items-center gap-4 rounded-xl border border-dashed p-4 transition-colors " +
                (file
                  ? "border-primary/40 bg-primary/5"
                  : "hover:border-primary/40 hover:bg-muted/40")
              }
            >
              <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                {file ? (
                  <FileSpreadsheet className="size-5" />
                ) : (
                  <Upload className="size-5" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {file ? file.name : "Choose a CSV or Excel file"}
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {file ? "Ready to upload" : "CSV, XLSX, or XLS"}
                </span>
              </span>
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="sr-only"
              />
            </label>
            <div className="flex items-start gap-2 rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
              <CircleHelp className="mt-0.5 size-4 shrink-0" />
              <p>
                Spreadsheet columns can be used as script placeholders such as{" "}
                <code className="rounded bg-background px-1 py-0.5 text-foreground">
                  {"{name}"}
                </code>{" "}
                ,
                <code className="rounded bg-background px-1 py-0.5 text-foreground">
                  {"{amount}"}
                </code>
                and{" "}
                <code className="rounded bg-background px-1 py-0.5 text-foreground">
                  {"{city}"}
                </code>
                . The phone column is detected automatically; enter a column
                name below to override it.
              </p>
            </div>
            <label className="block space-y-2 text-sm font-medium">
              Phone column{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
              <Input
                value={phoneColumn}
                onChange={(e) => setPhoneColumn(e.target.value)}
                placeholder="e.g. phone_number"
              />
            </label>
          </div>
          <div className="flex flex-col-reverse gap-2 border-t pt-5 sm:flex-row sm:justify-end">
            <Link
              href="/campaigns"
              className={buttonVariants({ variant: "outline" })}
            >
              Cancel
            </Link>
            <Button onClick={() => void submit()} disabled={busy || !agentId}>
              <Users className="mr-2 size-4" />
              {busy ? "Creating…" : "Create and start campaign"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
