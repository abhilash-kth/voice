"use client";

// Backend base URL (FastAPI on :8000). Override with NEXT_PUBLIC_BACKEND_URL.
const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const TOKEN_KEY = "va_token";

export function setToken(t: string) {
  if (typeof window !== "undefined") localStorage.setItem(TOKEN_KEY, t);
}
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
export function clearToken() {
  if (typeof window !== "undefined") localStorage.removeItem(TOKEN_KEY);
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* ignore */
    }
    throw Object.assign(new Error(detail || `Request failed (${res.status})`), {
      status: res.status,
    });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ------ types --------------------------------------------------------------
export interface ProviderDef {
  id: string;
  display_name: string;
  provider: string;
  tier: "free" | "paid";
  requires_key: boolean;
  options?: Record<string, string[]>;
  notes?: string;
  [k: string]: unknown;
}
export interface Catalog {
  catalog: {
    llm: ProviderDef[];
    stt: ProviderDef[];
    tts: ProviderDef[];
    telephony: ProviderDef[];
  };
  walletTopupAmounts: number[];
  server_cost_per_min?: number;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  greeting: string;
  language: string;
  voice_personality: string;
  client_rate_per_min: number;
  memory_enabled: boolean;
  recording_enabled: boolean;
  max_concurrency: number;
  enabled: boolean;
  created_at: string;
  agent_mode?: string;
  announce_text?: string;
  providers: {
    llm: { id: string; config: Record<string, unknown> };
    stt: { id: string; config: Record<string, unknown> };
    tts: { id: string; config: Record<string, unknown> };
    telephony?: { id: string; config: Record<string, unknown> };
  };
  knowledge: {
    text: string;
    documents: { name: string; content: string }[];
    system_prompt: string;
    faq: { q: string; a: string }[];
  };
  call_count?: number;
  total_billed?: number;
  active_calls?: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  wallet_balance: number;
  created_at: string;
}

export interface CallRecord {
  id: string;
  agent_id: string;
  mode: string;
  room: string;
  phone: string | null;
  status: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  transcripts: { role: string; text: string }[];
  recording_url?: string | null;
  usage: Record<string, unknown>;
  cost: Record<string, unknown>;
}

export interface Usage {
  walletBalance: number;
  totalCallsCount: number;
  totalMinutesUsed: number;
  currentMonthSpend: number;
  llmInputTokens: number;
  llmOutputTokens: number;
  ttsChars: number;
  sttSeconds: number;
  recentCalls: Record<string, unknown>[];
}

// ------ auth ---------------------------------------------------------------
export const register = (body: {
  email: string;
  password: string;
  name?: string;
}) =>
  req<{ token: string; user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const login = (body: { email: string; password: string }) =>
  req<{ token: string; user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const me = () => req<User>("/api/auth/me");

// ------ catalog / agents ---------------------------------------------------
export const getCatalog = () => req<Catalog>("/api/catalog");
export const listAgents = () => req<{ agents: Agent[] }>("/api/agents");
export const getAgent = (id: string) => req<Agent>(`/api/agents/${id}`);
export const createAgent = (body: Record<string, unknown>) =>
  req<Agent>("/api/agents", { method: "POST", body: JSON.stringify(body) });
export const updateAgent = (id: string, body: Record<string, unknown>) =>
  req<Agent>(`/api/agents/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const deleteAgent = (id: string) =>
  req<void>(`/api/agents/${id}`, { method: "DELETE" });

// ------ calls --------------------------------------------------------------
export const startCall = (body: {
  agent_id: string;
  mode: string;
  phone?: string;
  sip_trunk_id?: string;
}) =>
  req<{
    call_id: string;
    token?: string;
    agent_token?: string;
    url: string;
    room: string;
    mode: string;
  }>("/api/calls", { method: "POST", body: JSON.stringify(body) });
export const listCalls = () => req<{ calls: CallRecord[] }>("/api/calls");
export const getCall = (id: string) => req<CallRecord>(`/api/calls/${id}`);

// ------ campaigns (bulk calling) ------------------------------------------
export interface CampaignLead {
  index: number;
  data: Record<string, string>;
  status: "queued" | "calling" | "done" | "failed";
  call_id?: string;
  error?: string;
  updated_at?: string;
}
export interface Campaign {
  id: string;
  user_id: string;
  agent_id: string;
  name: string;
  concurrency: number;
  sip_trunk_id: string;
  phone_column: string;
  created_at: string;
  status: "paused" | "running" | "done";
  summary: {
    queued: number;
    calling: number;
    done: number;
    failed: number;
    total: number;
  };
  leads?: CampaignLead[];
}

export const createCampaign = async (form: FormData) => {
  const token = getToken();
  const res = await fetch(`${BASE}/api/campaigns`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok)
    throw new Error(
      (await res.json().catch(() => ({})))?.detail || "Campaign create failed",
    );
  return res.json();
};
export const listCampaigns = () =>
  req<{ campaigns: Campaign[] }>("/api/campaigns");
export const getCampaign = (id: string) =>
  req<Campaign>(`/api/campaigns/${id}`);
export const startCampaign = (id: string) =>
  req<Campaign>(`/api/campaigns/${id}/start`, { method: "POST" });
export const pauseCampaign = (id: string) =>
  req<Campaign>(`/api/campaigns/${id}/pause`, { method: "POST" });
export const deleteCampaign = (id: string) =>
  req<void>(`/api/campaigns/${id}`, { method: "DELETE" });

// ------ wallet / billing ---------------------------------------------------
export const getWallet = () =>
  req<{ balance: number; currency: string; transactions: unknown[] }>(
    "/api/wallet",
  );
export const recharge = (amount: number) =>
  req("/api/wallet/recharge", {
    method: "POST",
    body: JSON.stringify({ add_amount: amount }),
  });
export const getUsage = () => req<Usage>("/api/billing/usage");

// ------ knowledge ----------------------------------------------------------
export const setKnowledge = (
  agentId: string,
  body: {
    text?: string;
    system_prompt?: string;
    faq?: { q: string; a: string }[];
  },
) =>
  req<{ ok: boolean }>(`/api/agents/${agentId}/knowledge`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const addKnowledge = async (
  agentId: string,
  opts: { text?: string; faq?: { q: string; a: string }[]; file?: File },
) => {
  const form = new FormData();
  if (opts.text) form.set("text", opts.text);
  if (opts.faq) form.set("faq", JSON.stringify(opts.faq));
  if (opts.file) form.set("file", opts.file);
  const token = getToken();
  const res = await fetch(`${BASE}/api/agents/${agentId}/knowledge`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok)
    throw new Error(
      (await res.json().catch(() => ({})))?.detail || "Upload failed",
    );
  return res.json();
};

export { BASE };
