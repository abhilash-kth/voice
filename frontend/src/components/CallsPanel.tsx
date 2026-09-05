"use client";

import { useEffect, useState } from "react";
import { CallRecord, getCall, listCalls } from "@/lib/api";

const COST_LABELS: Record<string, string> = {
  stt_cost_inr: "STT",
  llm_cost_inr: "LLM",
  tts_cost_inr: "TTS",
  server_cost_inr: "Server",
  total_cost_inr: "Your Cost",
  client_price_inr: "Customer Bill",
  your_profit_inr: "Profit",
  your_cost_per_min: "Your cost/min",
  client_bill_per_min: "Bill/min",
};

export default function CallsPanel() {
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [detail, setDetail] = useState<CallRecord | null>(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const res = await listCalls();
      setCalls(res.calls);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const open = async (id: string) => {
    const d = await getCall(id);
    setDetail(d);
  };

  const costRows = detail?.cost as Record<string, number> | undefined;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800 overflow-x-auto">
        <h2 className="text-xl font-bold mb-4">📞 Call Log</h2>
        {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
        <table className="w-full text-left text-sm text-gray-300">
          <thead className="bg-gray-800 text-gray-400 uppercase text-xs">
            <tr>
              <th className="p-3">Call</th>
              <th className="p-3">Mode</th>
              <th className="p-3">Status</th>
              <th className="p-3">Duration</th>
              <th className="p-3">Billed</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {calls.length === 0 && <tr><td colSpan={6} className="p-3 text-gray-500">No calls yet.</td></tr>}
            {calls.map((c) => (
              <tr key={c.id} className="hover:bg-gray-800/50">
                <td className="p-3 font-mono text-blue-400">{c.id}</td>
                <td className="p-3">{c.mode}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded-full text-[11px] ${
                    c.status === "completed" ? "bg-green-500/20 text-green-300"
                    : c.status === "in-progress" ? "bg-blue-500/20 text-blue-300"
                    : "bg-gray-700 text-gray-300"}`}>
                    {c.status}
                  </span>
                </td>
                <td className="p-3">{c.duration_seconds}s</td>
                <td className="p-3 font-bold text-green-400">
                  ₹{(c.cost as any)?.client_price_inr ?? 0}
                </td>
                <td className="p-3">
                  <button onClick={() => open(c.id)} className="text-blue-400 hover:underline text-xs">view</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Transcript + cost detail */}
      <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800">
        <h2 className="text-xl font-bold mb-4">📝 Transcript & Cost</h2>
        {detail ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <span className="font-mono text-blue-400">{detail.id}</span>
              <span>·</span><span>{detail.mode}</span>
              <span>·</span><span>{detail.duration_seconds}s</span>
              {detail.recording_url && (
                <a href={detail.recording_url} target="_blank" rel="noreferrer"
                   className="text-blue-400 hover:underline">🎧 recording</a>
              )}
            </div>

            {(detail.usage as any)?.llm_input_tokens != null && (
              <div className="bg-gray-800/50 rounded-lg p-3 text-xs flex flex-wrap gap-3 mb-2">
                <span>Tokens <b className="text-blue-300">{(detail.usage as any).llm_input_tokens} in / {(detail.usage as any).llm_output_tokens} out</b></span>
                <span>TTS <b className="text-green-300">{(detail.usage as any).tts_chars} chars</b></span>
                <span>STT <b className="text-yellow-300">{(detail.usage as any).stt_seconds ?? 0}s</b></span>
              </div>
            )}

            {costRows && (
              <div className="bg-gray-800/50 rounded-lg p-3 text-sm">
                <p className="text-gray-400 text-xs uppercase mb-2">Cost breakdown (your cost vs customer price)</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(costRows).filter(([k]) => COST_LABELS[k]).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-gray-400">{COST_LABELS[k]}</span>
                      <span className={(k === "your_profit_inr" && v < 0) ? "text-red-400" : "text-white"}>
                        ₹{v}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-2 max-h-[380px] overflow-y-auto">
              {detail.transcripts.length === 0 && <p className="text-gray-500 text-sm">No transcript recorded.</p>}
              {detail.transcripts.map((t, i) => (
                <div key={i} className={`p-2 rounded-lg text-sm ${t.role === "user" ? "bg-blue-500/10 text-blue-100" : "bg-green-500/10 text-green-100"}`}>
                  <span className="text-[10px] uppercase opacity-60 mr-2">{t.role}</span>
                  {t.text}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="text-gray-500 text-sm p-6 text-center">
            Select a call to view the transcript, per-component cost, and recording.
          </div>
        )}
      </div>
    </div>
  );
}
