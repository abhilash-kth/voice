"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Agent,
  Catalog,
  getCatalog,
  listAgents,
  deleteAgent,
} from "@/lib/index";
import AgentConfigForm from "@/app/(workspace)/agents/components/AgentConfigForm";

export default function AgentsPage() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [notice, setNotice] = useState("");
  const [backendError, setBackendError] = useState("");

  const refreshAgents = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([getCatalog(), listAgents()]);
      setCatalog(c);
      setAgents(a.agents);
      setBackendError("");
    } catch (e) {
      setBackendError(
        "Could not reach the backend at localhost:8000. Start it with: uvicorn app.main:app --port 8000",
      );
    }
  }, []);

  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  const removeAgent = async (a: Agent) => {
    const ok = window.confirm(
      `Delete agent "${a.name}"? All of its call history will also be removed.`,
    );
    if (!ok) return;
    try {
      await deleteAgent(a.id);
      setNotice(`Deleted ${a.name}`);
      refreshAgents();
    } catch (e) {
      setNotice(`Could not delete: ${(e as Error).message}`);
    }
  };

  return (
    <div className="space-y-6">
      {/* Moved error banners here so they render correctly */}
      {backendError && (
        <div className="-mx-4 sm:-mx-6 -mt-4 sm:-mt-6 mb-6 bg-red-500/10 border-b border-red-500/20 text-red-300 text-sm px-4 sm:px-6 py-3 flex items-center gap-2">
          <span>⚠️</span> <span className="truncate">{backendError}</span>
        </div>
      )}
      {notice && (
        <div className="-mx-4 sm:-mx-6 -mt-4 sm:-mt-6 mb-6 bg-emerald-500/10 border-b border-emerald-500/20 text-emerald-300 text-sm px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
          <span className="truncate">{notice}</span>
          <button
            onClick={() => setNotice("")}
            className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-black tracking-tight">
            🤖 Agents
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Create & configure voice agents, then assign to calls.
          </p>
        </div>
        <button
          onClick={() => setEditing(null)}
          className="w-full sm:w-auto bg-white text-gray-900 hover:bg-gray-100 border border-white rounded-xl px-4 py-2.5 text-sm font-bold shadow-lg shadow-white/10 transition-all"
        >
          + New Agent
        </button>
      </div>

      {catalog && (
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-4 sm:p-6 shadow-xs">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">
            {editing ? `Editing: ${editing.name}` : "Create a new agent"}
          </h3>
          <AgentConfigForm
            key={editing?.id ?? "new"}
            catalog={catalog}
            editing={editing}
            onDone={(m) => {
              setNotice(m);
              setTimeout(() => setEditing(null), 600);
              refreshAgents();
            }}
          />
        </div>
      )}

      {!editing && agents.length === 0 && (
        <div className="bg-gray-900 rounded-2xl border border-dashed border-gray-800 p-12 text-center animate-fade-in-up">
          <div className="w-14 h-14 rounded-2xl bg-gray-800 flex items-center justify-center text-2xl mx-auto mb-4">
            🤖
          </div>
          <p className="text-sm font-semibold text-gray-300">No agents yet</p>
          <p className="text-xs text-gray-500 mt-1 max-w-[300px] mx-auto leading-relaxed">
            Fill in the form above — pick a provider, language and voice — and
            your first agent will be ready to take calls in seconds.
          </p>
        </div>
      )}

      {!editing && agents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((a) => (
            <div
              key={a.id}
              className="group bg-gray-900 rounded-2xl border border-gray-800 hover:border-gray-700 p-5 transition-all hover:shadow-xl hover:shadow-black/20 hover:-translate-y-0.5"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-bold text-[15px] truncate pr-2">
                  {a.name}
                </h3>
                <span
                  className={`text-[10px] px-2 py-1 rounded-full font-bold tracking-wider uppercase shrink-0 ${
                    a.enabled
                      ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                      : "bg-gray-800 text-gray-500 border border-gray-700"
                  }`}
                >
                  {a.enabled ? "active" : "disabled"}
                </span>
              </div>
              <p className="text-[13px] text-gray-400 mb-4 line-clamp-2 min-h-[36px]">
                {a.description || "—"}
              </p>
              <div className="flex flex-wrap gap-1.5 text-[11px] text-gray-400 mb-3">
                <span
                  className={`rounded-full px-2.5 py-1 border ${
                    a.agent_mode === "announcement"
                      ? "bg-blue-500/10 text-blue-300 border-blue-500/20"
                      : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                  }`}
                >
                  {a.agent_mode === "announcement"
                    ? "announcement"
                    : "assistant"}
                </span>
                <span className="bg-gray-800 border border-gray-700/50 rounded-full px-2.5 py-1">
                  LLM: {a.providers.llm.id.slice(0, 18)}
                </span>
                <span className="bg-gray-800 border border-gray-700/50 rounded-full px-2.5 py-1">
                  STT: {a.providers.stt.id.slice(0, 14)}
                </span>
                <span className="bg-gray-800 border border-gray-700/50 rounded-full px-2.5 py-1">
                  TTS: {a.providers.tts.id.slice(0, 14)}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5 text-[11px] mb-4">
                <span
                  className={`rounded-full px-2.5 py-1 border ${
                    a.memory_enabled
                      ? "bg-indigo-500/10 text-indigo-300 border-indigo-500/20"
                      : "bg-gray-800 text-gray-500 border-gray-700"
                  }`}
                >
                  memory {a.memory_enabled ? "on" : "off"}
                </span>
                <span
                  className={`rounded-full px-2.5 py-1 border ${
                    a.recording_enabled
                      ? "bg-red-500/10 text-red-300 border-red-500/20"
                      : "bg-gray-800 text-gray-500 border-gray-700"
                  }`}
                >
                  rec {a.recording_enabled ? "on" : "off"}
                </span>
                <span className="rounded-full px-2.5 py-1 bg-blue-500/10 text-blue-300 border border-blue-500/20">
                  ×{a.max_concurrency}
                </span>
              </div>
              <div className="flex justify-between text-xs text-gray-500 mb-4 bg-gray-800/50 rounded-xl px-3 py-2">
                <span>
                  {a.call_count ?? 0} calls · {a.active_calls ?? 0} live
                </span>
                <span className="font-bold text-white">
                  ₹{a.total_billed ?? 0}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <button
                  onClick={() => setEditing(a)}
                  className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-xl py-2 text-xs font-semibold transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={() => {
                    // Pass the preset ID in the URL instead of context state
                    router.push(`/dashboard/call?preset=${a.id}`);
                  }}
                  className="bg-white hover:bg-gray-100 text-gray-900 rounded-xl py-2 text-xs font-bold shadow-sm transition-colors"
                >
                  Call
                </button>
                <button
                  onClick={() => removeAgent(a)}
                  title="Delete this agent"
                  className="bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/20 rounded-xl py-2 text-xs font-semibold transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
