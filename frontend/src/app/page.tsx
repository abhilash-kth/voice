"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Agent,
  Catalog,
  User,
  getCatalog,
  listAgents,
  deleteAgent,
  me,
  getToken,
  clearToken,
} from "@/lib/api";
import AuthScreen from "@/components/AuthScreen";
import AgentConfigForm from "@/components/AgentConfigForm";
import CallPanel from "@/components/CallPanel";
import BillingPanel from "@/components/BillingPanel";
import CallsPanel from "@/components/CallsPanel";
import CampaignPanel from "@/components/CampaignPanel";

type Tab = "call" | "agents" | "billing" | "calls" | "campaigns";

export default function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState<Tab>("call");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [presetCallAgentId, setPresetCallAgentId] = useState("");
  const [notice, setNotice] = useState("");
  const [backendError, setBackendError] = useState("");

  // Restore session if a token exists.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setChecking(false);
      return;
    }
    me()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setChecking(false));
  }, []);

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
    if (user) refreshAgents();
  }, [user, refreshAgents]);

  const afterCall = useCallback(() => refreshAgents(), [refreshAgents]);

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

  if (checking) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        Loading…
      </div>
    );
  }
  if (!user) {
    return (
      <AuthScreen
        onAuth={(u) => {
          setUser(u);
        }}
      />
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "call", label: "📞 Call" },
    { id: "campaigns", label: "📣 Campaigns" },
    { id: "agents", label: "🤖 Agents" },
    { id: "billing", label: "💳 Wallet" },
    { id: "calls", label: "📊 Calls" },
  ];

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <header className="border-b border-gray-800 bg-gray-900/60 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-xl font-bold">
            K
          </div>
          <div>
            <h1 className="font-bold text-lg leading-tight">
              Voice Agent SaaS
            </h1>
            <p className="text-xs text-gray-400">
              Self-service multilingual agents on LiveKit
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <nav className="flex bg-gray-800/80 p-1 rounded-xl border border-gray-700">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-4 py-2 text-sm font-semibold rounded-lg transition-all ${
                  tab === t.id
                    ? "bg-blue-600 text-white shadow-md"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-2 text-sm">
            <div className="text-right leading-tight">
              <div className="font-semibold">{user.name || user.email}</div>
              <div className="text-[11px] text-gray-400">
                ₹{user.wallet_balance}
              </div>
            </div>
            <button
              onClick={() => {
                clearToken();
                setUser(null);
              }}
              className="text-xs text-gray-400 hover:text-white bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {backendError && (
        <div className="bg-red-500/10 border-b border-red-500/30 text-red-300 text-sm px-6 py-3">
          ⚠️ {backendError}
        </div>
      )}
      {notice && (
        <div className="bg-green-500/10 border-b border-green-500/30 text-green-300 text-sm px-6 py-3 flex items-center justify-between">
          <span>{notice}</span>
          <button
            onClick={() => setNotice("")}
            className="text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

      <main className="flex-1 p-6 max-w-7xl w-full mx-auto">
        {tab === "call" && (
          <CallPanel
            agents={agents}
            onStarted={afterCall}
            presetAgentId={presetCallAgentId}
            onPresetConsumed={() => setPresetCallAgentId("")}
          />
        )}

        {tab === "agents" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">🤖 Agents</h2>
                <p className="text-sm text-gray-400">
                  Create &amp; configure voice agents, then assign to calls.
                </p>
              </div>
              <button
                onClick={() => setEditing(null)}
                className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg px-4 py-2 text-sm"
              >
                + New Agent
              </button>
            </div>

            {catalog && (
              <div className="bg-gray-900 p-5 rounded-2xl border border-gray-800">
                <h3 className="text-sm font-bold text-gray-400 uppercase mb-4">
                  {editing ? `Editing: ${editing.name}` : "Create a new agent"}
                </h3>
                <AgentConfigForm
                  key={editing?.id ?? "new"}
                  catalog={catalog}
                  editing={editing}
                  onDone={(m) => {
                    setNotice(m);
                    setPresetCallAgentId("");
                    setTimeout(() => setEditing(null), 600);
                    refreshAgents();
                  }}
                />
              </div>
            )}

            {!editing && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {agents.map((a) => (
                  <div
                    key={a.id}
                    className="bg-gray-900 p-5 rounded-2xl border border-gray-800"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-bold text-lg">{a.name}</h3>
                      <span
                        className={`text-[11px] px-2 py-0.5 rounded-full ${a.enabled ? "bg-green-500/20 text-green-300" : "bg-gray-700"}`}
                      >
                        {a.enabled ? "active" : "disabled"}
                      </span>
                    </div>
                    <p className="text-sm text-gray-400 mb-3 line-clamp-2">
                      {a.description || "—"}
                    </p>
                    <div className="flex flex-wrap gap-2 text-[11px] text-gray-400 mb-3">
                      <span className="bg-gray-800 rounded px-2 py-0.5">
                        LLM: {a.providers.llm.id}
                      </span>
                      <span className="bg-gray-800 rounded px-2 py-0.5">
                        STT: {a.providers.stt.id}
                      </span>
                      <span className="bg-gray-800 rounded px-2 py-0.5">
                        TTS: {a.providers.tts.id}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px] mb-3">
                      <span
                        className={`rounded px-2 py-0.5 ${a.memory_enabled ? "bg-indigo-500/20 text-indigo-300" : "bg-gray-800 text-gray-500"}`}
                      >
                        memory {a.memory_enabled ? "on" : "off"}
                      </span>
                      <span
                        className={`rounded px-2 py-0.5 ${a.recording_enabled ? "bg-red-500/20 text-red-300" : "bg-gray-800 text-gray-500"}`}
                      >
                        record {a.recording_enabled ? "on" : "off"}
                      </span>
                      <span className="rounded px-2 py-0.5 bg-blue-500/20 text-blue-300">
                        ×{a.max_concurrency} concurrent
                      </span>
                    </div>
                    <div className="flex justify-between text-xs text-gray-500 mb-4">
                      <span>
                        {a.call_count ?? 0} calls · {a.active_calls ?? 0} live
                      </span>
                      <span>₹{a.total_billed ?? 0} billed</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setEditing(a);
                          setPresetCallAgentId("");
                          setTab("agents");
                        }}
                        className="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg py-2 text-sm"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => {
                          setEditing(null);
                          setPresetCallAgentId(a.id);
                          setTab("call");
                        }}
                        className="flex-1 bg-blue-600 hover:bg-blue-500 rounded-lg py-2 text-sm font-semibold"
                      >
                        Call
                      </button>
                      <button
                        onClick={() => removeAgent(a)}
                        title="Delete this agent"
                        className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 rounded-lg py-2 text-sm"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === "campaigns" && (
          <CampaignPanel agents={agents} onChanged={refreshAgents} />
        )}
        {tab === "billing" && <BillingPanel />}
        {tab === "calls" && <CallsPanel />}
      </main>
    </div>
  );
}
