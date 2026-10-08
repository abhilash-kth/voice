"use client";

// Session security: the JWT lives in an httpOnly, SameSite=Lax cookie that
// JavaScript can never read. No token is stored in localStorage anymore —
// these shims only keep older imports compiling.
import { BASE, req, cachedReq, invalidate } from "./request";

export function setToken(_t?: string) { /* cookie session — nothing to store */ }
export function getToken(): string | null { return null; }
export function clearToken() {
  // Best-effort server-side logout; ignore failures (session may already be gone).
  fetch(`${BASE}/api/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {});
  invalidate("/");
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
  // Super-Admin-configured bounds for the voice_speed slider.
  voice_speed?: { min: number; max: number; default: number };
  llm_providers?: { id: string; display_name: string; base_url: string; tier: string }[];
  llm_models?: {
    provider: string;
    model_id: string;
    display_name: string;
    base_url: string;
    input_price_per_1m: number;
    cached_input_price_per_1m: number;
    output_price_per_1m: number;
    context_window: number;
    max_output_tokens: number;
    reasoning_supported: boolean;
    reasoning_default: string;
    streaming_supported: boolean;
    tool_calling_supported: boolean;
    structured_output_supported: boolean;
    expected_speed: string;
    status: string;
    capabilities: string[];
    notes: string;
  }[];
  llm_by_provider?: Record<string, any[]>;
  llm_catalog?: any;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  greeting: string;
  language: string;
  // female | male | neutral — selects the spoken voice (Chirp 3 / Bulbul speaker)
  gender: string;
  // Normalized 0.6–1.6 (admin range); mapped per-TTS-provider where supported.
  voice_speed: number;
  voice_personality: string;
  no_response_timeout_seconds?: number;
  no_response_message?: string;
  client_rate_per_min: number;
  memory_enabled: boolean;
  recording_enabled: boolean;
  max_concurrency: number;
  enabled: boolean;
  created_at: string;
  agent_mode?: string;
  announce_text?: string;
  end_after_announcement?: boolean;
  fallback_response?: string;
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
  // "USER" | "SUPER_ADMIN" — SUPER_ADMIN users also get the /super-admin panel link.
  role?: string;
  disabled?: boolean;
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
  req<{ user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const login = (body: { email: string; password: string }) =>
  req<{ user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const me = () => req<User>("/api/auth/me");

// ------ catalog / agents ---------------------------------------------------
export const getCatalog = () => cachedReq<Catalog>("/api/catalog", 60_000);
export const listAgents = () => cachedReq<{ agents: Agent[] }>("/api/agents", 10_000);
export const getAgent = (id: string) => req<Agent>(`/api/agents/${id}`);
export const createAgent = async (body: Record<string, unknown>) => {
  const out = await req<Agent>("/api/agents", { method: "POST", body: JSON.stringify(body) });
  invalidate("/api/agents");
  return out;
};
export const updateAgent = async (id: string, body: Record<string, unknown>) => {
  const out = await req<Agent>(`/api/agents/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  invalidate("/api/agents");
  return out;
};
export const deleteAgent = async (id: string) => {
  const out = await req<void>(`/api/agents/${id}`, { method: "DELETE" });
  invalidate("/api/agents");
  return out;
};

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
export const endCall = (id: string) => req<{ ok: boolean; call_id: string }>(`/api/calls/${id}/end`, { method: "POST" });
export const deleteCall = (id: string) => req<void>(`/api/calls/${id}`, { method: "DELETE" });

export * from "./campaigns";

// ------ wallet / billing ---------------------------------------------------
export const getWallet = () =>
  cachedReq<{ balance: number; currency: string; transactions: unknown[] }>(
    "/api/wallet", 4_000,
  );
export const recharge = async (amount: number) => {
  const out = await req("/api/wallet/recharge", {
    method: "POST",
    body: JSON.stringify({ add_amount: amount }),
  });
  invalidate("/api/wallet");
  invalidate("/api/subscription");
  return out;
};
export const getUsage = () => req<Usage>("/api/billing/usage");

// ------ knowledge ----------------------------------------------------------
export const setKnowledge = (
  agentId: string,
  body: {
    text?: string;
    system_prompt?: string;
    faq?: { q: string; a: string }[];
    documents?: { name: string; content: string }[];
  },
) =>
  req<{ ok: boolean }>(`/api/agents/${agentId}/knowledge`, {
    method: "PUT",
    body: JSON.stringify(body),
  }).then((out) => { invalidate("/api/agents"); return out; });

export const addKnowledge = async (
  agentId: string,
  opts: { text?: string; faq?: { q: string; a: string }[]; file?: File },
) => {
  const form = new FormData();
  if (opts.text) form.set("text", opts.text);
  if (opts.faq) form.set("faq", JSON.stringify(opts.faq));
  if (opts.file) form.set("file", opts.file);
  const res = await fetch(`${BASE}/api/agents/${agentId}/knowledge`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok)
    throw new Error(
      (await res.json().catch(() => ({})))?.detail || "Upload failed",
    );
  invalidate("/api/agents");
  return res.json();
};

// ------ call cost preview (mode + models + concurrency pricing) -----------
export interface CostPreview {
  client_price_inr: number;
  client_rate_per_min: number;
  duration_mins: number;
  total_cost_inr: number;
  models_rate_per_min: number;   // selected LLM+STT+TTS rate card
  server_per_min: number;        // platform server cost component
  rate_card_per_min: number;     // models + server
  mode_min_per_min: number;      // per-mode minimum that applies
  applied_rate_per_min: number;  // max(rate_card, mode_min)
  floor_applied?: boolean;
  [k: string]: unknown;
}
export const costPreview = (body: {
  duration_seconds?: number; stt_seconds?: number;
  llm_input_tokens?: number; llm_output_tokens?: number; tts_chars?: number;
  llm_provider_id?: string; stt_provider_id?: string; tts_provider_id?: string;
  agent_mode?: string; max_concurrency?: number;
}) => req<CostPreview>("/api/cost-preview", { method: "POST", body: JSON.stringify(body) });

export { BASE };
