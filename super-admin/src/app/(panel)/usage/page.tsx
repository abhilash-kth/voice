"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox } from "@/components/PageHeader";
import { listUsage, type UsageRow } from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtINR, shortId } from "@/lib/format";

function userDisplay(r: UsageRow): string {
  if (r.user_name) return r.user_email ? `${r.user_name} (${r.user_email})` : r.user_name;
  return r.user_email || shortId(r.user_id);
}

export default function UsagePage() {
  const [items, setItems] = useState<UsageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listUsage()
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const totals = items.reduce(
    (acc, r) => ({
      billed: acc.billed + r.client_price_inr,
      cost: acc.cost + r.total_cost_inr,
      profit: acc.profit + r.profit_inr,
      seconds: acc.seconds + r.duration_seconds,
    }),
    { billed: 0, cost: 0, profit: 0, seconds: 0 }
  );

  return (
    <>
      <PageHeader title="Usage" subtitle={`Per-call cost & profit — latest ${items.length} calls`}>
        <button className="btn-secondary text-xs" onClick={load} disabled={loading}>↻ Refresh</button>
      </PageHeader>

      {items.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <TotalCard label="Talk time" value={fmtDuration(totals.seconds)} />
          <TotalCard label="Billed to customers" value={fmtINR(totals.billed)} accent="text-emerald-300" />
          <TotalCard label="Provider cost" value={fmtINR(totals.cost)} accent="text-red-300" />
          <TotalCard label="Gross profit" value={fmtINR(totals.profit)} accent="text-blue-300" />
        </div>
      )}

      <StateBox loading={loading} error={error} empty={items.length === 0 ? "No calls recorded yet." : null}>
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Started</th>
                <th>User</th>
                <th>Agent</th>
                <th>Mode</th>
                <th>Duration</th>
                <th className="text-right">STT sec</th>
                <th className="text-right">LLM tk (in/out)</th>
                <th className="text-right">TTS chars</th>
                <th className="text-right">Billed</th>
                <th className="text-right">Cost</th>
                <th className="text-right">Profit</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td className="text-gray-400 text-xs whitespace-nowrap">{fmtDateTime(r.started_at)}</td>
                  <td>
                    <div className="text-gray-200 text-sm">{userDisplay(r)}</div>
                    <div className="font-mono text-xs text-gray-500">{shortId(r.user_id)}</div>
                  </td>
                  <td className="font-mono text-xs text-gray-400">{shortId(r.agent_id)}</td>
                  <td><span className="pill pill-gray">{r.mode || "voice"}</span></td>
                  <td className="text-gray-300 text-xs">{fmtDuration(r.duration_seconds)}</td>
                  <td className="text-right text-gray-400 text-xs">{r.stt_seconds}</td>
                  <td className="text-right text-gray-400 text-xs">{r.llm_input_tokens}/{r.llm_output_tokens}</td>
                  <td className="text-right text-gray-400 text-xs">{r.tts_chars}</td>
                  <td className="text-right font-semibold text-emerald-300">{fmtINR(r.client_price_inr)}</td>
                  <td className="text-right text-red-300/80">{fmtINR(r.total_cost_inr)}</td>
                  <td className="text-right font-semibold text-blue-300">{fmtINR(r.profit_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-600 mt-2">
          Billed = what the customer paid. Cost = what providers charged you. Profit = billed − cost.
        </p>
      </StateBox>
    </>
  );
}

function TotalCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-xl font-black mt-1 ${accent || "text-white"}`}>{value}</div>
    </div>
  );
}
