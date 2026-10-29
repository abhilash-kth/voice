"use client";

// Backend base URL (FastAPI on :9000). Override with NEXT_PUBLIC_BACKEND_URL.
const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export const TOKEN_KEY = "va_session";   // separate key from the customer dashboard token

export async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: "include", // sends the cookie
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch { }
    const err = Object.assign(new Error(detail || `Request failed (${res.status})`), {
      status: res.status,
    });
    if (
      (res.status === 401 || res.status === 403) &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login") &&
      path !== "/api/auth/logout"
    ) {
      // the cookie is httpOnly, so only the backend can clear it
      await fetch(`${BASE}/api/auth/logout`, { method: "POST", credentials: "include" }).catch(() => { });
      window.location.href = "/login";
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
  req<{ user: ApiUser }>("/api/auth/login", { method: "POST", body: JSON.stringify(body) });
export const logout = () => req<unknown>("/api/auth/logout", { method: "POST" });
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

// ------ billing ----------------------------------------------------------------
export interface BillingConfig {
  server_cost_per_min: number;
  min_client_price: number;
  profit_margin_percent: number;
  wallet_topup_amounts: number[];
  voice_speed_min: number;
  voice_speed_max: number;
  voice_speed_default: number;
  [k: string]: unknown;
}
export const getBilling = () => req<BillingConfig>("/api/admin/billing");
export const updateBilling = (patch: Partial<BillingConfig>) =>
  req<BillingConfig>("/api/admin/billing", { method: "PUT", body: JSON.stringify(patch) });

// ------ usage + audit ------------------------------------------------------------
export interface UsageRow {
  id: string;
  user_id: string;
  user_name: string;
  user_email: string;
  agent_id: string;
  mode: string;
  status: string;
  started_at: string;
  ended_at: string;
  phone: string;
  room: string;
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
export interface AdminEndCallResult {
  ok: boolean;
  call_id: string;
  status: string;
  already_ended: boolean;
  room_deleted: boolean;
}
export const endAdminCall = (id: string) =>
  req<AdminEndCallResult>(`/api/admin/calls/${id}/end`, { method: "POST" });

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

// ------ telephony marketplace ----------------------------------------------
export interface TelephonyOverview {
  configured: boolean;
  config: {
    source?: "super_admin" | "environment_fallback" | string;
    api_base_url: string;
    voicelink_sip: string;
    livekit_sip: string;
    tech_prefix: string;
    wallet_bypass: boolean;
    kyc_finalize_verified: boolean;
    kyc_terms_configured: boolean;
    default_trunk_configured?: boolean;
    frontend_url?: string;
    public_api_url?: string;
    updated_at?: string;
  };
  provider_profile: Record<string, unknown> | null;
  provider_error: string;
  counts: {
    accounts: number;
    numbers: number;
    purchases: number;
    accounts_by_kyc: Record<string, number>;
    numbers_by_status: Record<string, number>;
    purchases_by_state: Record<string, number>;
  };
}

export interface TelephonyAccount {
  id: string;
  user_id: string;
  user_email?: string;
  user_name?: string;
  client_id: string;
  username: string;
  email: string;
  name: string;
  phone: string;
  status: string;
  kyc_status: string;
  kyc_step: string;
  kyc_meta: Record<string, unknown>;
  wallet_balance: number;
  channels_allocated: number;
  channels_available: number;
  numbers_count?: number;
  last_error: string;
  last_synced_at: string;
  created_at: string;
  updated_at: string;
}

export interface TelephonyAssignedAgent {
  id: string;
  name: string;
  purpose: string;
  enabled: boolean;
}

export interface TelephonyNumber {
  id: string;
  user_id: string;
  user_email?: string;
  user_name?: string;
  voice_link_account_id: string | null;
  number: string;
  country_code: string;
  status: string;
  provisioning_step: string;
  source: string;
  channels: number;
  monthly_rate: number;
  expires_at: string;
  provider_did_id: string;
  provider_purchase_id: string;
  sip_username: string;
  sip_password_masked: string;
  has_sip_password: boolean;
  voice_link_trunk_id: string;
  voice_link_routing_id: string;
  livekit_outbound_trunk_id: string;
  livekit_inbound_trunk_id: string;
  livekit_dispatch_rule_id: string;
  inbound_agent_id: string | null;
  dial_prefix: string;
  last_error: string;
  agents?: TelephonyAssignedAgent[];
  created_at: string;
  updated_at: string;
}

export interface TelephonyPurchase {
  id: string;
  user_id: string;
  user_email?: string;
  user_name?: string;
  voice_link_account_id: string;
  phone_number_id: string | null;
  provider_did_id: string;
  number: string;
  months: number;
  channels: number;
  provider_order_id: string;
  provider_purchase_id: string;
  quote_total: number;
  monthly_rate: number;
  customer_charge: number;
  state: string;
  error: string;
  expires_at: string;
  created_at: string;
  updated_at: string;
}

export interface TelephonyAccountDetail {
  account: TelephonyAccount;
  numbers: TelephonyNumber[];
  purchases: TelephonyPurchase[];
}

const qsOf = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  return qs.toString() ? `?${qs}` : "";
};

export interface TelephonySettings {
  source: "super_admin" | "environment_fallback" | string;
  configured: boolean;
  encryption_key_configured: boolean;
  default_sip_trunk_id: string;
  voicelink_api_base_url: string;
  voicelink_api_token_configured: boolean;
  voicelink_api_token_masked: string;
  voicelink_username: string;
  voicelink_password_configured: boolean;
  voicelink_password_masked: string;
  voicelink_shared_trunk_username: string;
  voicelink_shared_trunk_password_configured: boolean;
  voicelink_shared_trunk_password_masked: string;
  voicelink_sip_host: string;
  voicelink_sip_port: number;
  voicelink_tech_prefix: string;
  voicelink_transport_type: number;
  voicelink_audio_formats: string[];
  voicelink_wallet_bypass: boolean;
  voicelink_kyc_terms_url: string;
  voicelink_kyc_redirect_hosts: string[];
  kyc_finalize_verified: boolean;
  livekit_sip_host: string;
  livekit_sip_port: number;
  frontend_url: string;
  public_api_url: string;
  updated_at: string;
}

export interface TelephonySettingsPatch {
  default_sip_trunk_id?: string;
  voicelink_api_base_url?: string;
  voicelink_api_token?: string;
  clear_voicelink_api_token?: boolean;
  voicelink_username?: string;
  voicelink_password?: string;
  clear_voicelink_password?: boolean;
  voicelink_shared_trunk_username?: string;
  voicelink_shared_trunk_password?: string;
  clear_voicelink_shared_trunk_password?: boolean;
  voicelink_sip_host?: string;
  voicelink_sip_port?: number;
  voicelink_tech_prefix?: string;
  voicelink_transport_type?: number;
  voicelink_audio_formats?: string[];
  voicelink_wallet_bypass?: boolean;
  voicelink_kyc_terms_url?: string;
  voicelink_kyc_redirect_hosts?: string[];
  kyc_finalize_verified?: boolean;
  livekit_sip_host?: string;
  livekit_sip_port?: number;
  frontend_url?: string;
  public_api_url?: string;
}

export interface TelephonySettingsTest {
  ok: boolean;
  profile: {
    id?: string;
    active?: boolean;
    verified?: boolean;
    billing_mode?: string;
    wallet_balance?: number;
    channels_available?: number;
    plan_name?: string;
    [key: string]: unknown;
  } | null;
}

export const getTelephonySettings = () =>
  req<{ settings: TelephonySettings }>("/api/admin/telephony/settings");

export const updateTelephonySettings = (body: TelephonySettingsPatch) =>
  req<{ settings: TelephonySettings }>("/api/admin/telephony/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const testTelephonySettings = () =>
  req<TelephonySettingsTest>("/api/admin/telephony/settings/test", {
    method: "POST",
  });

export const getTelephonyOverview = () =>
  req<TelephonyOverview>("/api/admin/telephony/overview");

export const listTelephonyAccounts = (params: {
  page?: number;
  page_size?: number;
  q?: string;
  kyc_status?: string;
  status?: string;
} = {}) =>
  req<Paged<TelephonyAccount>>(`/api/admin/telephony/accounts${qsOf(params)}`);

export const getTelephonyAccount = (id: string) =>
  req<TelephonyAccountDetail>(`/api/admin/telephony/accounts/${id}`);

export const syncTelephonyAccount = (id: string) =>
  req<TelephonyAccountDetail>(`/api/admin/telephony/accounts/${id}/sync`, {
    method: "POST",
  });

export const allocateTelephonyWallet = (
  id: string,
  amount: number,
  description = "Operator allocation",
) =>
  req<TelephonyAccount>(`/api/admin/telephony/accounts/${id}/allocate-wallet`, {
    method: "POST",
    body: JSON.stringify({ amount, description }),
  });

export const setTelephonyAccountStatus = (
  id: string,
  status: "active" | "suspended",
) =>
  req<TelephonyAccount>(`/api/admin/telephony/accounts/${id}/status`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });

export const listTelephonyNumbers = (params: {
  page?: number;
  page_size?: number;
  q?: string;
  status?: string;
  user_id?: string;
} = {}) =>
  req<Paged<TelephonyNumber>>(`/api/admin/telephony/numbers${qsOf(params)}`);

export const retryTelephonyNumber = (id: string) =>
  req<TelephonyNumber>(`/api/admin/telephony/numbers/${id}/retry-provision`, {
    method: "POST",
  });

export const syncTelephonyInbound = (id: string) =>
  req<TelephonyNumber>(`/api/admin/telephony/numbers/${id}/sync-inbound`, {
    method: "POST",
  });

export const setTelephonyNumberStatus = (
  id: string,
  status: "active" | "suspended",
) =>
  req<TelephonyNumber>(`/api/admin/telephony/numbers/${id}/status`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });

export interface ManualNumberBody {
  user_id: string;
  number: string;
  livekit_outbound_trunk_id?: string;
  livekit_inbound_trunk_id?: string;
  dial_prefix?: string;
  channels?: number;
  expires_at?: string;
}

export const createManualTelephonyNumber = (body: ManualNumberBody) =>
  req<TelephonyNumber>("/api/admin/telephony/numbers/manual", {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface ManualNumberUpdateBody {
  number?: string;
  livekit_outbound_trunk_id?: string;
  livekit_inbound_trunk_id?: string;
  dial_prefix?: string;
  channels?: number;
  expires_at?: string;
}

export const updateManualTelephonyNumber = (
  id: string,
  body: ManualNumberUpdateBody,
) =>
  req<TelephonyNumber>(`/api/admin/telephony/numbers/${id}/manual`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export interface DeleteManualNumberResult {
  ok: boolean;
  id: string;
  number: string;
  unassigned_agent_ids: string[];
}

export const deleteManualTelephonyNumber = (id: string) =>
  req<DeleteManualNumberResult>(`/api/admin/telephony/numbers/${id}/manual`, {
    method: "DELETE",
  });

export const listTelephonyPurchases = (params: {
  page?: number;
  page_size?: number;
  state?: string;
} = {}) =>
  req<Paged<TelephonyPurchase>>(`/api/admin/telephony/purchases${qsOf(params)}`);

export { BASE };
