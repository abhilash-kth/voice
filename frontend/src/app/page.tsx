"use client";

// Dashboard orchestrator — visuals live in components/* (≤300-line rule):
//   components/TopBar.tsx    sticky header + nav + wallet pill
//   components/AgentsTab.tsx agents tab (form + card grid)
//   CallPanel / BillingPanel / CallsPanel / CampaignPanel  the other tabs
import { useCallback, useEffect, useState } from "react";
import {
  Agent, Catalog, User,
  getCatalog, listAgents, deleteAgent, me, getWallet,
} from "@/lib/api";
import AuthScreen from "@/components/AuthScreen";
import TopBar, { Tab } from "@/components/TopBar";
import AgentsTab from "@/components/AgentsTab";
import CallPanel from "@/components/CallPanel";
import BillingPanel from "@/components/BillingPanel";
import CallsPanel from "@/components/CallsPanel";
import CampaignPanel from "@/components/CampaignPanel";

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
  // P10: flips true on the first successful agents fetch and stays true.
  // CallPanel disables Start until then — first-call success must not
  // depend on a page refresh.
  const [agentsReady, setAgentsReady] = useState(false);
  const [walletBalance, setWalletBalance] = useState<number | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    // Session is an httpOnly cookie (JS can't see it) — probe the server
    // instead of checking localStorage. 401 → AuthScreen.
    me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);

  const refreshAgents = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([getCatalog(), listAgents()]);
      setCatalog(c);
      setAgents(a.agents);
      setBackendError("");
      setAgentsReady(true);
    } catch (e) {
      setBackendError(
        "Could not reach the backend. Start it with: uvicorn app.main:app --port 8000",
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
    return <AuthScreen onAuth={(u) => setUser(u)} />;
  }

  const displayBalance = walletBalance ?? user.wallet_balance;

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex flex-col">
      <TopBar
        user={user}
        tab={tab}
        onTab={setTab}
        balance={displayBalance}
        mobileMenuOpen={mobileMenuOpen}
        onMobileMenu={setMobileMenuOpen}
        onLogout={() => setUser(null)}
      />

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
            agentsReady={agentsReady}
          />
        )}

        {tab === "agents" && (
          <AgentsTab
            catalog={catalog}
            agents={agents}
            editing={editing}
            onEdit={(a) => { setEditing(a); setPresetCallAgentId(""); }}
            onFormDone={(m) => {
              setNotice(m);
              setPresetCallAgentId("");
              setTimeout(() => setEditing(null), 600);
              refreshAgents();
            }}
            onStartCall={(a) => {
              setEditing(null);
              setPresetCallAgentId(a.id);
              setTab("call");
            }}
            onDelete={removeAgent}
          />
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
