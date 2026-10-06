"use client";

// Backend base URL (FastAPI on :8000). Override with NEXT_PUBLIC_BACKEND_URL.
const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const TOKEN_KEY = "sa_token";   // separate key from the customer dashboard token

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

export async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
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
    const err = Object.assign(new Error(detail || `Request failed (${res.status})`), {
      status: res.status,
    });
    // Session expired or no longer authorized → bounce to login.
    if (res.status === 401 || res.status === 403) {
      clearToken();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ------ shared types --------------------------------------------------------
export interface ApiUser {
  id: string;
  email: string;
  name: string;
  role?: string;
  disabled?: boolean;
  wallet_balance?: number;
  created_at?: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ------ auth ----------------------------------------------------------------
export const login = (body: { email: string; password: string }) =>
  req<{ token: string; user: ApiUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const me = () => req<ApiUser>("/api/auth/me");

// ------ stats / health -------------------------------------------------------
export interface Stats {
  users: number;
  calls: number;
  providers: number;
  models: number;
  enabled_providers: number;
  enabled_models: number;
  wallet_balance_total: number;
  wallet_recharge_total: number;
}
export interface AdminHealth {
  ok: boolean;
  snapshot_source: string;
  snapshot_ts: number;   // Unix epoch SECONDS (from time.time()), not a string
  snapshot_error?: string | null;
}
export const adminStats = () => req<Stats>("/api/admin/stats");
export const adminHealth = () => req<AdminHealth>("/api/admin/health");
export const reloadConfig = () =>
  req<{ ok: boolean; source: string; ts: number }>("/api/admin/config/reload", { method: "POST" });
export const reseedConfig = () =>
  req<{ ok: boolean; source: string }>("/api/admin/config/reseed", { method: "POST" });

// ------ users ----------------------------------------------------------------
export const listUsers = (params: { page?: number; page_size?: number; q?: string; role?: string; disabled?: boolean }) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.q) qs.set("q", params.q);
  if (params.role) qs.set("role", params.role);
  if (params.disabled !== undefined) qs.set("disabled", String(params.disabled));
  return req<Paged<ApiUser>>(`/api/admin/users?${qs.toString()}`);
};

export interface UserDetail {
  user: ApiUser;
  agents: Record<string, unknown>[];
  calls: Record<string, unknown>[];
  wallet: { balance: number; currency: string; transactions: Record<string, unknown>[] };
  usage: {
    walletBalance: number;
    totalCallsCount: number;
    totalMinutesUsed: number;
    currentMonthSpend: number;
    llmInputTokens: number;
    llmOutputTokens: number;
    ttsChars: number;
    sttSeconds: number;
    recentCalls: Record<string, unknown>[];
  };
}
export const getUserDetail = (id: string) => req<UserDetail>(`/api/admin/users/${id}`);
export const setUserRole = (id: string, role: "USER" | "SUPER_ADMIN") =>
  req<ApiUser>(`/api/admin/users/${id}/role`, { method: "PUT", body: JSON.stringify({ role }) });
export const setUserDisabled = (id: string, disabled: boolean) =>
  req<ApiUser>(`/api/admin/users/${id}/disabled`, { method: "PUT", body: JSON.stringify({ disabled }) });
export const adjustWallet = (id: string, amount: number, note: string) =>
  req<UserDetail["wallet"]>(`/api/admin/users/${id}/wallet`, {
    method: "POST",
    body: JSON.stringify({ amount, note }),
  });

// ------ providers ------------------------------------------------------------
export interface Provider {
  id: string;
  kind: string;
  slug: string;
  display_name: string;
  adapter: string;
  base_url: string;
  key_env: string;
  tier: string;
  requires_key: boolean;
  enabled: boolean;
  status: string;
  notes: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}
export const listProviders = (kind?: string) =>
  req<{ items: Provider[] }>(`/api/admin/providers${kind ? `?kind=${kind}` : ""}`);
export const createProvider = (body: Partial<Provider> & { kind: string; slug: string }) =>
  req<Provider>("/api/admin/providers", { method: "POST", body: JSON.stringify(body) });
export const updateProvider = (id: string, patch: Partial<Provider>) =>
  req<Provider>(`/api/admin/providers/${id}`, { method: "PUT", body: JSON.stringify(patch) });
export const deleteProvider = (id: string, cascade = false) =>
  req<void>(`/api/admin/providers/${id}?cascade=${cascade}`, { method: "DELETE" });

// ------ catalog models --------------------------------------------------------
export interface CatalogModel {
  id: string;
  kind: string;
  provider_id: string;
  provider_slug: string;
  catalog_id: string;
  model_id: string;
  display_name: string;
  enabled: boolean;
  status: string;
  tier: string;
  customer_price_per_min: number;
  price_currency: string;
  input_price_per_1m: number;
  cached_input_price_per_1m: number;
  output_price_per_1m: number;
  cost_per_min: number;
  cost_per_1k_chars: number;
  meta: Record<string, unknown>;
  sort_order: number;
  created_at: string;
  updated_at: string;
}
export const listModels = (params: { kind?: string; provider_id?: string; page?: number; page_size?: number }) => {
  const qs = new URLSearchParams();
  if (params.kind) qs.set("kind", params.kind);
  if (params.provider_id) qs.set("provider_id", params.provider_id);
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  return req<Paged<CatalogModel>>(`/api/admin/models?${qs.toString()}`);
};
export const createModel = (body: Partial<CatalogModel> & { kind: string; provider_id: string; catalog_id: string }) =>
  req<CatalogModel>("/api/admin/models", { method: "POST", body: JSON.stringify(body) });
export const updateModel = (id: string, patch: Partial<CatalogModel>) =>
  req<CatalogModel>(`/api/admin/models/${id}`, { method: "PUT", body: JSON.stringify(patch) });
export const deleteModel = (id: string) =>
  req<void>(`/api/admin/models/${id}`, { method: "DELETE" });

// ------ credentials ------------------------------------------------------------
export interface Credential {
  id: string;
  provider_id: string;
  provider_slug: string;
  kind: string;
  label: string;
  masked_value: string;
  status: string;
  created_at: string;
  updated_at: string;
}
export const listCredentials = (params: { provider_id?: string; kind?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.provider_id) qs.set("provider_id", params.provider_id);
  if (params.kind) qs.set("kind", params.kind);
  return req<{ items: Credential[] }>(`/api/admin/credentials${qs.toString() ? `?${qs}` : ""}`);
};
export const createCredential = (body: { provider_id: string; value: string; label?: string }) =>
  req<Credential>("/api/admin/credentials", { method: "POST", body: JSON.stringify(body) });
export const updateCredential = (id: string, patch: { value?: string; label?: string }) =>
  req<Credential>(`/api/admin/credentials/${id}`, { method: "PUT", body: JSON.stringify(patch) });
export const setCredentialStatus = (id: string, status: "active" | "disabled" | "rotated") =>
  req<Credential>(`/api/admin/credentials/${id}/status`, { method: "PUT", body: JSON.stringify({ status }) });
export const rotateCredential = (id: string, new_value: string, label?: string) =>
  req<Credential>(`/api/admin/credentials/${id}/rotate`, {
    method: "POST",
    body: JSON.stringify({ new_value, label: label ?? "" }),
  });
// Audited: returns the plaintext key ONCE for display in the panel only.
export const revealCredential = (id: string) =>
  req<{ value: string }>(`/api/admin/credentials/${id}/reveal`, { method: "POST" });
export const deleteCredential = (id: string) =>
  req<void>(`/api/admin/credentials/${id}`, { method: "DELETE" });
// Billing types/helpers moved to lib/billing.ts (file-size budget).

// ------ usage + audit ------------------------------------------------------------
export interface UsageRow {
  id: string;
  user_id: string;
  agent_id: string;
  mode: string;
  status: string;
  started_at: string;
  duration_seconds: number;
  stt_seconds: number;
  llm_input_tokens: number;
  llm_output_tokens: number;
  tts_chars: number;
  client_price_inr: number;
  total_cost_inr: number;
  profit_inr: number;
}
export const listUsage = () => req<{ items: UsageRow[] }>("/api/admin/usage");

export interface AuditLog {
  id: string;
  admin_id: string;
  admin_email: string;
  action: string;
  target_type: string;
  target_id: string;
  detail: Record<string, unknown>;
  created_at: string;   // ISO string (backend field name is created_at, not ts)
}
export const listAuditLogs = (params: { page?: number; page_size?: number; action?: string; target_type?: string; q?: string }) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.action) qs.set("action", params.action);
  if (params.target_type) qs.set("target_type", params.target_type);
  if (params.q) qs.set("q", params.q);
  return req<Paged<AuditLog>>(`/api/admin/audit-logs?${qs.toString()}`);
};

export { BASE };
