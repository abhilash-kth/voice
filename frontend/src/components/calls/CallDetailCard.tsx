"use client";
import { CallRecord } from "@/lib/api";
import { callBilled, callRatePerMin, formatDate, formatDuration } from "./format";

/** Right-hand column of the Calls tab: billing summary + transcript. */
export default function CallDetailCard({ detail }: { detail: CallRecord | null }) {
  const cost = detail?.cost as any;
  const totalBilled = callBilled(cost);
  const ratePerMin = callRatePerMin(cost);
  const durationMins = cost?.duration_mins ?? cost?.durationMins
    ?? (detail ? (detail.duration_seconds / 60).toFixed(2) : 0);

  return (
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
  );
}
