"use client";
import { useEffect, useState } from "react";
import { Agent } from "@/lib/api";

/**
 * "New Bulk-Call Campaign" form — owns its field state and hands a ready
 * FormData up to the panel, which performs the API call (single error path).
 */
export default function CreateForm({
  agents, onSubmit,
}: {
  agents: Agent[];
  onSubmit: (form: FormData) => Promise<string | null>;   // null on success, else error text
}) {
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [concurrency, setConcurrency] = useState(5);
  const [sipTrunkId, setSipTrunkId] = useState("");
  const [phoneColumn, setPhoneColumn] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!agentId && agents.length) setAgentId(agents[0].id);
  }, [agents, agentId]);

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
      const failed = await onSubmit(form);
      if (failed) setErr(failed);
      else {
        setFile(null);
        setName("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
      <h2 className="text-xl font-bold mb-4">📣 New Bulk-Call Campaign</h2>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-gray-400 font-medium">Campaign name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. EMI reminder — Jan batch"
            className="input mt-1"
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 font-medium">Agent</label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="input mt-1"
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
            <label className="text-xs text-gray-400 font-medium">Concurrent calls</label>
            <input
              type="number"
              min={1}
              value={concurrency}
              onChange={(e) => setConcurrency(Number(e.target.value))}
              className="input mt-1"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">SIP trunk ID</label>
            <input
              value={sipTrunkId}
              onChange={(e) => setSipTrunkId(e.target.value)}
              placeholder="default / ST_xxxx"
              className="input mt-1"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-400 font-medium">Lead file (.csv / .xlsx)</label>
          <label className={`mt-1 flex items-center gap-3 rounded-xl border border-dashed px-4 py-3 cursor-pointer transition-colors ${file ? "border-emerald-500/40 bg-emerald-500/5" : "border-gray-700 bg-gray-800/40 hover:border-gray-600 hover:bg-gray-800/70"}`}>
            <span className={`w-9 h-9 rounded-lg flex items-center justify-center text-base shrink-0 ${file ? "bg-emerald-500/15" : "bg-gray-700/60"}`}>
              {file ? "✅" : "📄"}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-white truncate">
                {file ? file.name : "Choose lead file"}
              </span>
              <span className="block text-[11px] text-gray-500">
                {file ? "Ready to upload" : "CSV or Excel with one row per lead"}
              </span>
            </span>
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="hidden"
            />
          </label>
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
            className="input mt-1"
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
  );
}
