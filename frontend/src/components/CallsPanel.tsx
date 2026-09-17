"use client";

import { useEffect, useState } from "react";
import { CallRecord, deleteCall, getCall, listCalls } from "@/lib/api";

function formatDuration(sec: number) {
  if (!sec) return "0s";
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

function formatDate(d: string) {
  try {
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return d;
  }
}

export default function CallsPanel() {
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [detail, setDetail] = useState<CallRecord | null>(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
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
  };

  useEffect(() => {
    load();
  }, []);

  const open = async (id: string) => {
    try {
      const d = await getCall(id);
      setDetail(d);
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

  const cost = detail?.cost as any;
  const totalBilled = cost?.client_price_inr ?? cost?.clientPrice ?? 0;
  const ratePerMin = cost?.client_bill_per_min ?? cost?.client_rate_per_min ?? cost?.billPerMin ?? cost?.clientRatePerMin ?? 0;
  const durationMins = cost?.duration_mins ?? cost?.durationMins ?? (detail ? (detail.duration_seconds / 60).toFixed(2) : 0);

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
                  const cCost: any = c.cost || {};
                  const billed = cCost.client_price_inr ?? cCost.clientPrice ?? 0;
                  const rate = cCost.client_bill_per_min ?? cCost.client_rate_per_min ?? cCost.billPerMin ?? "-";
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

        {/* Detail */}
        <div className="xl:col-span-2 bg-[#111827] rounded-2xl border border-gray-800 shadow-xl overflow-hidden flex flex-col">
          <div className="p-4 border-b border-gray-800">
            <h3 className="font-semibold text-white">Call Details</h3>
            <p className="text-xs text-gray-400 mt-1">Billing and transcript for selected call</p>
          </div>

          {detail ? (
            <div className="p-5 space-y-5 overflow-y-auto max-h-[720px]">
              {/* Meta */}
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-gray-300 font-mono">{detail.id}</span>
                <span className="px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700">{detail.mode}</span>
                <span
                  className={`px-2.5 py-1 rounded-full border text-[11px] font-medium ${
                    detail.status === "completed"
                      ? "bg-green-500/10 text-green-300 border-green-500/20"
                      : detail.status === "in-progress"
                        ? "bg-blue-500/10 text-blue-300 border-blue-500/20"
                        : "bg-gray-800 text-gray-300"
                  }`}
                >
                  {detail.status}
                </span>
                {detail.recording_url && (
                  <a
                    href={detail.recording_url}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2.5 py-1 rounded-full bg-blue-600/20 text-blue-300 border border-blue-500/20 hover:bg-blue-600/30"
                  >
                    🎧 Recording
                  </a>
                )}
              </div>

              {/* Business billing card */}
              <div className="bg-gradient-to-br from-gray-800 to-gray-800/60 rounded-xl border border-gray-700 p-4">
                <h4 className="text-xs uppercase tracking-wider text-gray-400 font-semibold mb-3">Billing Summary</h4>
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-gray-900/60 rounded-lg p-3 border border-gray-800">
                    <p className="text-[11px] text-gray-500 uppercase">Duration</p>
                    <p className="text-lg font-bold text-white mt-1">{formatDuration(detail.duration_seconds)}</p>
                    <p className="text-[11px] text-gray-400 mt-0.5">{durationMins} billable min</p>
                  </div>
                  <div className="bg-gray-900/60 rounded-lg p-3 border border-gray-800">
                    <p className="text-[11px] text-gray-500 uppercase">Rate</p>
                    <p className="text-lg font-bold text-blue-300 mt-1">₹{ratePerMin}</p>
                    <p className="text-[11px] text-gray-400 mt-0.5">per minute</p>
                  </div>
                  <div className="bg-green-600/10 rounded-lg p-3 border border-green-500/20">
                    <p className="text-[11px] text-green-300/70 uppercase">Total Billed</p>
                    <p className="text-lg font-bold text-green-300 mt-1">₹{totalBilled}</p>
                    <p className="text-[11px] text-green-300/60 mt-0.5">customer charge</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-gray-500">
                  <span>📅 {formatDate(detail.started_at)}</span>
                  {detail.ended_at && <span>• Ended {formatDate(detail.ended_at)}</span>}
                  <span>• {detail.mode} call</span>
                </div>
              </div>

              {/* Transcript */}
              <div>
                <h4 className="text-xs uppercase tracking-wider text-gray-400 font-semibold mb-3 flex items-center justify-between">
                  <span>Transcript</span>
                  <span className="text-[11px] bg-gray-800 px-2 py-0.5 rounded-full">{detail.transcripts.length} messages</span>
                </h4>
                <div className="space-y-2.5 max-h-[340px] overflow-y-auto pr-1">
                  {detail.transcripts.length === 0 && <p className="text-gray-500 text-sm p-4 text-center bg-gray-800/30 rounded-lg">No transcript recorded.</p>}
                  {detail.transcripts.map((t, i) => (
                    <div
                      key={i}
                      className={`p-3 rounded-xl text-sm border ${
                        t.role === "user"
                          ? "bg-blue-500/10 border-blue-500/20 text-blue-100 ml-4"
                          : "bg-gray-800 border-gray-700 text-gray-100 mr-4"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${t.role === "user" ? "bg-blue-500/20 text-blue-300" : "bg-gray-700 text-gray-300"}`}>
                          {t.role === "user" ? "Customer" : "Agent"}
                        </span>
                      </div>
                      <p className="leading-relaxed">{t.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
              <div className="w-16 h-16 rounded-2xl bg-gray-800 flex items-center justify-center text-2xl mb-4">📋</div>
              <p className="text-white font-medium">No call selected</p>
              <p className="text-sm text-gray-500 mt-1 max-w-[240px]">Select a call from the left to view billing, transcript, and recording.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
