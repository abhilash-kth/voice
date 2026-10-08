"use client";

// Call History tab — visuals live in ./calls/* (≤300-line rule):
//   calls/CallDetailCard.tsx  billing summary + transcript column
//   calls/format.ts           duration/date/cost-key helpers
import { useCallback, useEffect, useState } from "react";
import { CallRecord, deleteCall, getCall, listCalls } from "@/lib/api";
import CallDetailCard from "./calls/CallDetailCard";
import { callBilled, callRatePerMin, formatDate, formatDuration } from "./calls/format";

export default function CallsPanel() {
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [detail, setDetail] = useState<CallRecord | null>(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listCalls();
      // sort newest first
      const sorted = [...res.calls].sort((a, b) => {
        const da = new Date(a.started_at || "").getTime();
        const db = new Date(b.started_at || "").getTime();
        return db - da;
      });
      setCalls(sorted);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const open = async (id: string) => {
    try {
      setDetail(await getCall(id));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const deleteOne = async (id: string) => {
    if (!window.confirm("Delete this call record? This cannot be undone.")) return;
    setDeleting(true);
    try {
      await deleteCall(id);
      setCalls((items) => items.filter((c) => c.id !== id));
      setSelected((ids) => ids.filter((x) => x !== id));
      if (detail?.id === id) setDetail(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  const deleteSelected = async () => {
    if (!selected.length || !window.confirm(`Delete ${selected.length} selected call record(s)? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await Promise.all(selected.map((id) => deleteCall(id)));
      if (detail && selected.includes(detail.id)) setDetail(null);
      setCalls((items) => items.filter((c) => !selected.includes(c.id)));
      setSelected([]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">📞 Call History</h2>
          <p className="text-sm text-gray-400 mt-1">View your customer calls, billing, and transcripts. Internal costs are hidden for a clean business view.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm font-medium hover:bg-gray-700 transition"
          >
            ↻ Refresh
          </button>
          <button
            type="button"
            onClick={deleteSelected}
            disabled={!selected.length || deleting}
            className="rounded-lg bg-red-600 hover:bg-red-500 px-4 py-2 text-sm font-semibold disabled:opacity-40 transition"
          >
            {deleting ? "Deleting..." : `Delete ${selected.length ? `(${selected.length})` : "selected"}`}
          </button>
        </div>
      </div>

      {err && <div className="bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-lg p-3">{err}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
        {/* List */}
        <div className="xl:col-span-3 bg-[#111827] rounded-2xl border border-gray-800 shadow-xl overflow-hidden">
          <div className="p-4 border-b border-gray-800 flex items-center justify-between">
            <h3 className="font-semibold text-white">Recent Calls</h3>
            <span className="text-xs text-gray-400 bg-gray-800 px-2 py-1 rounded-full">{calls.length} total</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-800/60 text-gray-400 uppercase text-[11px] tracking-wider">
                <tr>
                  <th className="p-3 w-8">
                    <input
                      aria-label="Select all"
                      type="checkbox"
                      checked={calls.length > 0 && selected.length === calls.length}
                      onChange={(e) => setSelected(e.target.checked ? calls.map((c) => c.id) : [])}
                      className="rounded"
                    />
                  </th>
                  <th className="p-3">Call ID</th>
                  <th className="p-3">Date</th>
                  <th className="p-3">Mode</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Duration</th>
                  <th className="p-3 text-right">Rate/min</th>
                  <th className="p-3 text-right">Total</th>
                  <th className="p-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/80">
                {loading && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-gray-500">
                      Loading calls...
                    </td>
                  </tr>
                )}
                {!loading && calls.length === 0 && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-gray-500">
                      No calls yet. Start a call to see it here.
                    </td>
                  </tr>
                )}
                {calls.map((c) => {
                  const billed = callBilled(c.cost);
                  const rate = callRatePerMin(c.cost);
                  return (
                    <tr
                      key={c.id}
                      onClick={() => open(c.id)}
                      className={`hover:bg-gray-800/60 cursor-pointer transition-colors group ${detail?.id === c.id ? "bg-blue-600/10" : ""}`}
                    >
                      <td className="p-3">
                        <input
                          aria-label={`Select ${c.id}`}
                          type="checkbox"
                          onClick={(e) => e.stopPropagation()}
                          checked={selected.includes(c.id)}
                          onChange={(e) => setSelected((ids) => (e.target.checked ? [...ids, c.id] : ids.filter((id) => id !== c.id)))}
                          className="rounded"
                        />
                      </td>
                      <td className="p-3">
                        <span className="font-mono text-blue-400 group-hover:text-blue-300 text-xs">{c.id.slice(0, 12)}...</span>
                        <div className="text-[11px] text-gray-500">{c.agent_id?.slice(0, 12) || "agent"}</div>
                      </td>
                      <td className="p-3 text-gray-300 text-xs whitespace-nowrap">{formatDate(c.started_at)}</td>
                      <td className="p-3">
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 border border-gray-700">{c.mode}</span>
                      </td>
                      <td className="p-3">
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium border ${
                            c.status === "completed"
                              ? "bg-green-500/10 text-green-300 border-green-500/20"
                              : c.status === "in-progress"
                                ? "bg-blue-500/10 text-blue-300 border-blue-500/20 animate-pulse"
                                : c.status === "failed"
                                  ? "bg-red-500/10 text-red-300 border-red-500/20"
                                  : "bg-gray-700 text-gray-300 border-gray-600"
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>
                      <td className="p-3 text-gray-300 font-medium">{formatDuration(c.duration_seconds)}</td>
                      <td className="p-3 text-right text-gray-400 text-xs">₹{rate}</td>
                      <td className="p-3 text-right font-bold text-white">₹{billed}</td>
                      <td className="p-3 text-right">
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              open(c.id);
                            }}
                            className="text-blue-400 hover:text-blue-300 text-xs font-medium"
                          >
                            View
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteOne(c.id);
                            }}
                            disabled={deleting}
                            className="text-gray-500 hover:text-red-400 text-xs"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <CallDetailCard detail={detail} />
      </div>
    </div>
  );
}
