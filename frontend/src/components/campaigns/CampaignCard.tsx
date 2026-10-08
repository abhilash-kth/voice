"use client";
import { Campaign, CampaignLead } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  running: "bg-green-500/20 text-green-300",
  paused: "bg-yellow-500/20 text-yellow-300",
  done: "bg-blue-500/20 text-blue-300",
  failed: "bg-red-500/20 text-red-300",
  calling: "bg-yellow-500/20 text-yellow-300",
  queued: "bg-gray-700 text-gray-300",
};

/** One campaign card: progress, stats or live lead table, and actions. */
export default function CampaignCard({
  campaign: c, isOpen, onToggleOpen, onAction, onDelete,
}: {
  campaign: Campaign;
  isOpen: boolean;
  onToggleOpen: () => void;
  onAction: (action: "start" | "pause") => void;
  onDelete: () => void;
}) {
  const pct = c.summary.total > 0
    ? Math.round(((c.summary.done + c.summary.failed) / c.summary.total) * 100)
    : 0;

  return (
    <div className="group bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-gray-700 transition-all hover:shadow-xl hover:shadow-black/20 animate-fade-in-up">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-bold truncate pr-3">{c.name}</h3>
        <span
          className={`text-[11px] px-2.5 py-1 rounded-full font-semibold shrink-0 ${STATUS_COLOR[c.status]} ${c.status === "running" ? "animate-pulse" : ""}`}
        >
          {c.status}
        </span>
      </div>
      {/* progress */}
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 rounded-full transition-all duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[11px] text-gray-500 font-medium whitespace-nowrap">{pct}%</span>
      </div>

      {isOpen && c.leads ? (
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
              {c.phone_column}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center mb-3">
            <Stat label="Done" value={c.summary.done} color="text-green-400" />
            <Stat label="Calling" value={c.summary.calling} color="text-yellow-400" />
            <Stat label="Queued" value={c.summary.queued} color="text-gray-300" />
            <Stat label="Failed" value={c.summary.failed} color="text-red-400" />
          </div>
        </>
      )}

      <div className="flex gap-2 mt-3">
        {c.status === "running" ? (
          <button
            onClick={() => onAction("pause")}
            className="flex-1 bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 rounded-lg py-2 text-sm"
          >
            Pause
          </button>
        ) : (
          <button
            onClick={() => onAction("start")}
            className="flex-1 bg-green-600 hover:bg-green-500 rounded-lg py-2 text-sm font-semibold"
          >
            {c.status === "done" ? "Re-run" : "Start"}
          </button>
        )}
        <button
          onClick={onToggleOpen}
          className="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg py-2 text-sm"
        >
          {isOpen ? "Hide list" : "View leads"}
        </button>
        <button
          onClick={onDelete}
          title="Delete"
          className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 rounded-lg py-2 text-sm"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-gray-800/60 rounded-lg py-2">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase">{label}</div>
    </div>
  );
}

function LeadTable({ leads, phoneColumn }: {
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
