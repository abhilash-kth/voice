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
  getWallet,
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
  const [walletBalance, setWalletBalance] = useState<number | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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

  const refreshWallet = useCallback(async () => {
    try {
      const w = await getWallet();
      setWalletBalance(w.balance);
    } catch {}
  }, []);

  useEffect(() => {
    if (user) {
      refreshAgents();
      refreshWallet();
      const id = setInterval(() => {
        refreshWallet();
        // also refresh user to keep header balance in sync
        me().then(setUser).catch(() => {});
      }, 5000);
      return () => clearInterval(id);
    }
  }, [user, refreshAgents, refreshWallet]);

  const afterCall = useCallback(() => {
    refreshAgents();
    refreshWallet();
  }, [refreshAgents, refreshWallet]);

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
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-gray-400">Loading workspace...</p>
        </div>
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

  const tabs: { id: Tab; label: string; short: string }[] = [
    { id: "call", label: "📞 Call", short: "Call" },
    { id: "campaigns", label: "📣 Campaigns", short: "Campaigns" },
    { id: "agents", label: "🤖 Agents", short: "Agents" },
    { id: "billing", label: "💳 Wallet", short: "Wallet" },
    { id: "calls", label: "📊 Calls", short: "Calls" },
  ];

  const displayBalance = walletBalance ?? user.wallet_balance;

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex flex-col">
      {/* Professional responsive header */}
      <header className="border-b border-gray-800/80 bg-gray-900/70 backdrop-blur-xl sticky top-0 z-50">
        <div className="px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-lg font-black shadow-lg shadow-blue-600/20 shrink-0">
              K
            </div>
            <div className="hidden sm:block min-w-0">
              <h1 className="font-bold text-[15px] leading-tight tracking-tight">
                Voice Agent SaaS
              </h1>
              <p className="text-[11px] text-gray-400 truncate">
                Self-service multilingual agents on LiveKit
              </p>
            </div>
            <div className="sm:hidden">
              <h1 className="font-bold text-sm">Voice SaaS</h1>
            </div>
          </div>

          {/* Desktop nav */}
          <div className="hidden lg:flex items-center gap-3">
            <nav className="flex bg-gray-800/60 p-1 rounded-xl border border-gray-700/50 backdrop-blur">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-3.5 py-2 text-[13px] font-semibold rounded-lg transition-all ${
                    tab === t.id
                      ? "bg-white text-gray-900 shadow-md"
                      : "text-gray-400 hover:text-white hover:bg-gray-700/50"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>

            <div className="flex items-center gap-3 pl-3 border-l border-gray-800">
              <div className="flex items-center gap-2.5 bg-gray-800/80 border border-gray-700/50 rounded-xl px-3 py-2">
                <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 text-xs">₹</div>
                <div className="leading-tight">
                  <p className="text-[11px] text-gray-400 font-medium">Balance</p>
                  <p className="text-sm font-bold text-white">₹{displayBalance.toFixed(2)}</p>
                </div>
                <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse ml-1" />
              </div>

              <div className="text-right leading-tight hidden xl:block">
                <div className="font-semibold text-sm truncate max-w-[140px]">{user.name || user.email}</div>
                <div className="text-[11px] text-gray-500">Auto-deduct per call</div>
              </div>

              <button
                onClick={() => {
                  clearToken();
                  setUser(null);
                }}
                className="text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg px-3 py-2 transition-colors"
              >
                Logout
              </button>
            </div>
          </div>

          {/* Mobile: wallet + menu */}
          <div className="flex lg:hidden items-center gap-2">
            <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-xl px-2.5 py-1.5">
              <span className="text-[11px] font-bold text-emerald-400">₹{displayBalance.toFixed(2)}</span>
            </div>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="w-9 h-9 rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-400"
            >
              {mobileMenuOpen ? "✕" : "☰"}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="lg:hidden border-t border-gray-800 bg-gray-900/95 backdrop-blur-xl px-4 py-4 space-y-4">
            <nav className="grid grid-cols-3 gap-2">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setTab(t.id);
                    setMobileMenuOpen(false);
                  }}
                  className={`px-3 py-2.5 text-[13px] font-semibold rounded-xl border transition-all ${
                    tab === t.id
                      ? "bg-white text-gray-900 border-white shadow"
                      : "bg-gray-800 border-gray-700 text-gray-400"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
            <div className="flex items-center justify-between pt-3 border-t border-gray-800">
              <div>
                <p className="text-sm font-semibold">{user.name || user.email}</p>
                <p className="text-[11px] text-gray-500">Balance auto-deducts per call</p>
              </div>
              <button
                onClick={() => {
                  clearToken();
                  setUser(null);
                }}
                className="text-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-400"
              >
                Logout
              </button>
            </div>
          </div>
        )}

        {/* Mobile secondary nav - scrollable */}
        <div className="lg:hidden border-t border-gray-800/50 bg-gray-900/50 px-2 py-2 overflow-x-auto scrollbar-hide">
          <div className="flex gap-1.5 w-max">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3.5 py-1.5 text-xs font-semibold rounded-full whitespace-nowrap border transition-all ${
                  tab === t.id
                    ? "bg-white text-gray-900 border-white"
                    : "bg-gray-800 border-gray-700 text-gray-400"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {backendError && (
        <div className="bg-red-500/10 border-b border-red-500/20 text-red-300 text-sm px-4 sm:px-6 py-3 flex items-center gap-2">
          <span>⚠️</span> <span className="truncate">{backendError}</span>
        </div>
      )}
      {notice && (
        <div className="bg-emerald-500/10 border-b border-emerald-500/20 text-emerald-300 text-sm px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
          <span className="truncate">{notice}</span>
          <button
            onClick={() => setNotice("")}
            className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

      <main className="flex-1 p-4 sm:p-6 max-w-7xl w-full mx-auto">
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
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h2 className="text-xl sm:text-2xl font-black tracking-tight">🤖 Agents</h2>
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
              <div className="bg-gray-900 rounded-2xl border border-gray-800 p-4 sm:p-6 shadow-sm">
                <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">
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
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {agents.map((a) => (
                  <div
                    key={a.id}
                    className="group bg-gray-900 rounded-2xl border border-gray-800 hover:border-gray-700 p-5 transition-all hover:shadow-xl hover:shadow-black/20 hover:-translate-y-0.5"
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-bold text-[15px] truncate pr-2">{a.name}</h3>
                      <span
                        className={`text-[10px] px-2 py-1 rounded-full font-bold tracking-wider uppercase shrink-0 ${a.enabled ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20" : "bg-gray-800 text-gray-500 border border-gray-700"}`}
                      >
                        {a.enabled ? "active" : "disabled"}
                      </span>
                    </div>
                    <p className="text-[13px] text-gray-400 mb-4 line-clamp-2 min-h-[36px]">
                      {a.description || "—"}
                    </p>
                    <div className="flex flex-wrap gap-1.5 text-[11px] text-gray-400 mb-3">
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
                        className={`rounded-full px-2.5 py-1 border ${a.memory_enabled ? "bg-indigo-500/10 text-indigo-300 border-indigo-500/20" : "bg-gray-800 text-gray-500 border-gray-700"}`}
                      >
                        memory {a.memory_enabled ? "on" : "off"}
                      </span>
                      <span
                        className={`rounded-full px-2.5 py-1 border ${a.recording_enabled ? "bg-red-500/10 text-red-300 border-red-500/20" : "bg-gray-800 text-gray-500 border-gray-700"}`}
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
                      <span className="font-bold text-white">₹{a.total_billed ?? 0}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <button
                        onClick={() => {
                          setEditing(a);
                          setPresetCallAgentId("");
                          setTab("agents");
                        }}
                        className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-xl py-2 text-xs font-semibold transition-colors"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => {
                          setEditing(null);
                          setPresetCallAgentId(a.id);
                          setTab("call");
                        }}
                        className="bg-white hover:bg-gray-100 text-gray-900 rounded-xl py-2 text-xs font-bold shadow transition-colors"
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
        )}

        {tab === "campaigns" && (
          <CampaignPanel agents={agents} onChanged={refreshAgents} />
        )}
        {tab === "billing" && <BillingPanel />}
        {tab === "calls" && <CallsPanel />}
      </main>

      <footer className="border-t border-gray-800/50 bg-gray-900/30 px-4 sm:px-6 py-3 text-[11px] text-gray-600 flex flex-col sm:flex-row items-center justify-between gap-2">
        <span>© 2026 Voice Agent SaaS • Wallet auto-deducts per call • Remaining balance updates live</span>
        <span className="flex items-center gap-2">
          <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" /> Live billing
        </span>
      </footer>
    </div>
  );
}
