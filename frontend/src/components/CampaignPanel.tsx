"use client";

import { useEffect, useState } from "react";
import {
  Agent,
  Campaign,
  CampaignLead,
  createCampaign,
  listCampaigns,
  startCampaign,
  pauseCampaign,
  deleteCampaign,
  getCampaign,
} from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  running: "bg-green-500/20 text-green-300",
  paused: "bg-yellow-500/20 text-yellow-300",
  done: "bg-blue-500/20 text-blue-300",
  failed: "bg-red-500/20 text-red-300",
  calling: "bg-yellow-500/20 text-yellow-300",
  queued: "bg-gray-700 text-gray-300",
};

export default function CampaignPanel({
  agents,
  onChanged,
}: {
  agents: Agent[];
  onChanged?: () => void;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [active, setActive] = useState<Campaign | null>(null);

  // create form
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [concurrency, setConcurrency] = useState(5);
  const [sipTrunkId, setSipTrunkId] = useState("");
  const [phoneColumn, setPhoneColumn] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const res = await listCampaigns();
      setCampaigns(res.campaigns);
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!agentId && agents.length) setAgentId(agents[0].id);
  }, [agents, agentId]);

  // Poll the open campaign detail so per-lead status updates live.
  useEffect(() => {
    if (!campaignId) return;
    const iv = setInterval(async () => {
      try {
        const c = await getCampaign(campaignId);
        setActive(c);
      } catch {
        /* ignore transient polling errors */
      }
    }, 2500);
    return () => clearInterval(iv);
  }, [campaignId]);

  const open = async (id: string) => {
    setCampaignId(id);
    try {
      setActive(await getCampaign(id));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const submit = async () => {
    setErr("");
    if (!agentId) return setErr("Select an agent first.");
    if (!file) return setErr("Upload a .csv or .xlsx lead file.");
    setBusy(true);
    try {
      const form = new FormData();
      form.set("name", name || "Campaign");
      form.set("agent_id", agentId);
      form.set("concurrency", String(concurrency || 1));
      if (sipTrunkId) form.set("sip_trunk_id", sipTrunkId);
      if (phoneColumn) form.set("phone_column", phoneColumn);
      form.set("autostart", "true");
      form.set("file", file);
      const c = await createCampaign(form);
      setFile(null);
      setName("");
      await load();
      onChanged?.();
      await open(c.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (id: string, action: "start" | "pause") => {
    try {
      if (action === "start") await startCampaign(id);
      else await pauseCampaign(id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this campaign and its lead list?")) return;
    try {
      await deleteCampaign(id);
      if (campaignId === id) {
        setCampaignId("");
        setActive(null);
      }
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const topCard: Campaign[] = active
    ? [active, ...campaigns.filter((c) => c.id !== active.id)]
    : campaigns;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: create */}
        <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
          <h2 className="text-xl font-bold mb-4">📣 New Bulk-Call Campaign</h2>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 font-medium">
                Campaign name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. EMI reminder — Jan batch"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">Agent</label>
              <select
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-400 font-medium">
                  Concurrent calls
                </label>
                <input
                  type="number"
                  min={1}
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 font-medium">
                  SIP trunk ID
                </label>
                <input
                  value={sipTrunkId}
                  onChange={(e) => setSipTrunkId(e.target.value)}
                  placeholder="default / ST_xxxx"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">
                Lead file (.csv / .xlsx)
              </label>
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-400 mt-1 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-white"
              />
              <p className="text-[11px] text-gray-500 mt-1">
                Columns become the dynamic script placeholders —{" "}
                <code className="text-blue-300">{"{name}"}</code>{" "}
                <code className="text-blue-300">{"{amount}"}</code>{" "}
                <code className="text-blue-300">{"{city}"}</code>… The phone
                column is auto-detected (override below if needed).
              </p>
              <input
                value={phoneColumn}
                onChange={(e) => setPhoneColumn(e.target.value)}
                placeholder="Phone column (optional)"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            {err && (
              <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                {err}
              </div>
            )}
            <button
              onClick={submit}
              disabled={busy}
              className="w-full bg-green-600 hover:bg-green-500 text-white font-bold py-3 rounded-xl disabled:opacity-50"
            >
              {busy ? "Creating…" : "🚀 Create & Start Campaign"}
            </button>
          </div>
        </div>

        {/* Right: list */}
        <div className="space-y-4">
          <h2 className="text-xl font-bold">Your Campaigns</h2>
          {topCard.length === 0 && (
            <div className="bg-gray-900 p-8 rounded-2xl border border-gray-800 text-center text-gray-500">
              No campaigns yet. Create one on the left.
            </div>
          )}
          {topCard.map((c) => (
            <div
              key={c.id}
              className="bg-gray-900 p-5 rounded-2xl border border-gray-800"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-bold">{c.name}</h3>
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-full ${STATUS_COLOR[c.status]}`}
                >
                  {c.status}
                </span>
              </div>
              {active?.id === c.id && c.leads ? (
                <LeadTable leads={c.leads} phoneColumn={c.phone_column} />
              ) : (
                <>
                  <div className="flex flex-wrap gap-2 text-[11px] text-gray-400 mb-2">
                    <span className="bg-gray-800 rounded px-2 py-0.5">
                      ×{c.concurrency} concurrent
                    </span>
                    <span className="bg-gray-800 rounded px-2 py-0.5">
                      {c.summary.total} leads
                    </span>
                    <span className="bg-gray-800 rounded px-2 py-0.5">
                      {c.phone_column}?
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-center mb-3">
                    <Stat
                      label="Done"
                      value={c.summary.done}
                      color="text-green-400"
                    />
                    <Stat
                      label="Calling"
                      value={c.summary.calling}
                      color="text-yellow-400"
                    />
                    <Stat
                      label="Queued"
                      value={c.summary.queued}
                      color="text-gray-300"
                    />
                    <Stat
                      label="Failed"
                      value={c.summary.failed}
                      color="text-red-400"
                    />
                  </div>
                </>
              )}
              <div className="flex gap-2 mt-3">
                {c.status === "running" ? (
                  <button
                    onClick={() => act(c.id, "pause")}
                    className="flex-1 bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 rounded-lg py-2 text-sm"
                  >
                    Pause
                  </button>
                ) : (
                  <button
                    onClick={() => act(c.id, "start")}
                    className="flex-1 bg-green-600 hover:bg-green-500 rounded-lg py-2 text-sm font-semibold"
                  >
                    {c.status === "done" ? "Re-run" : "Start"}
                  </button>
                )}
                <button
                  onClick={() =>
                    active?.id === c.id ? setCampaignId("") : open(c.id)
                  }
                  className="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg py-2 text-sm"
                >
                  {active?.id === c.id ? "Hide list" : "View leads"}
                </button>
                <button
                  onClick={() => remove(c.id)}
                  title="Delete"
                  className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 rounded-lg py-2 text-sm"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="bg-gray-800/60 rounded-lg py-2">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase">{label}</div>
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
  return (
    <div className="overflow-x-auto max-h-64 overflow-y-auto rounded-lg border border-gray-800 mb-2">
      <table className="w-full text-left text-xs text-gray-300">
        <thead className="bg-gray-800 text-gray-400 uppercase sticky top-0">
          <tr>
            <th className="p-2">Phone</th>
            {headers
              .filter((h) => h !== phoneColumn)
              .slice(0, 4)
              .map((h) => (
                <th key={h} className="p-2">
                  {h}
                </th>
              ))}
            <th className="p-2">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {leads.map((l) => (
            <tr key={l.index} className="hover:bg-gray-800/40">
              <td className="p-2 font-mono">{l.data?.[phoneColumn] ?? ""}</td>
              {headers
                .filter((h) => h !== phoneColumn)
                .slice(0, 4)
                .map((h) => (
                  <td key={h} className="p-2">
                    {l.data?.[h] ?? ""}
                  </td>
                ))}
              <td className="p-2">
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded-full ${STATUS_COLOR[l.status]}`}
                >
                  {l.status}
                </span>
                {l.error && (
                  <span className="block text-[10px] text-red-400">
                    {l.error}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
