// Self-service telephony marketplace API (Phone Numbers page + agent form).
// Customers only ever see KYC progress, balances and their numbers — no
// provider ids for trunks, no SIP credentials.
import { BASE, invalidate, req } from "./request";

export type AgentPurpose = "outbound" | "inbound" | "both";

export interface PhoneNumberRecord {
  id: string;
  number: string;
  status: string;
  provisioning_step: string;
  source: string;
  channels: number;
  monthly_rate: number;
  expires_at: string;
  inbound_agent_id?: string | null;
  last_error: string;
  created_at: string;
  updated_at: string;
  [k: string]: unknown;
}

export interface VoiceLinkAccount {
  id: string;
  email: string;
  name: string;
  phone: string;
  status: string;
  kyc_status: string;
  kyc_step: string;
  wallet_balance: number;
  channels_allocated: number;
  channels_available: number;
  last_error: string;
  last_synced_at: string;
  [k: string]: unknown;
}

export interface KycState {
  status: string;
  step: string;
  account_type: string;
  documents: Record<string, { verified: boolean; uploaded: boolean }>;
  ready_for_submission: boolean;
  agreement_needs_acceptance: boolean;
  final_submission_available: boolean;
  terms_url: string;
}

export interface PhonePurchase {
  id: string;
  number: string;
  months: number;
  channels: number;
  quote_total: number;
  monthly_rate: number;
  customer_charge: number;
  state: string;
  error: string;
  expires_at: string;
  confirmation_available?: boolean;
  warning?: string;
  phone_number?: PhoneNumberRecord | null;
  [k: string]: unknown;
}

export interface TelephonyOverview {
  configured: boolean;
  plan_channels?: number;
  effective_channels?: number;
  provider: {
    did_type_rates: { type_id: string; name: string; monthly_rate: number }[];
    monthly_channel_rate: number;
    plan_name: string;
  } | null;
  provider_error: string;
  account: VoiceLinkAccount | null;
  kyc: KycState | null;
  numbers: PhoneNumberRecord[];
  latest_purchase: PhonePurchase | null;
  wallet: { balance: number; currency: string; transactions: unknown[] };
}

export interface AvailableNumber {
  id: string;
  number: string;
  type_label: string;
  monthly_rate: number;
  country_code: string;
}

export const getTelephonyOverview = () =>
  req<TelephonyOverview>("/api/telephony/overview");

export const listPhoneNumbers = () =>
  req<{ numbers: PhoneNumberRecord[] }>("/api/telephony/numbers");

export const setupPhoneAccount = async (body: { name?: string; phone?: string }) => {
  const out = await req<{ account: VoiceLinkAccount; kyc: KycState }>(
    "/api/telephony/account/setup",
    { method: "POST", body: JSON.stringify(body) },
  );
  invalidate("/api/telephony");
  return out;
};

export const syncPhoneAccount = async () => {
  const out = await req<{
    account: VoiceLinkAccount;
    kyc: KycState;
    numbers: PhoneNumberRecord[];
    imported: number;
  }>("/api/telephony/account/sync", { method: "POST" });
  invalidate("/api/telephony");
  return out;
};

export const getKyc = () =>
  req<{ kyc: KycState; account: VoiceLinkAccount }>("/api/telephony/kyc");

export const kycAction = async (body: Record<string, unknown>) => {
  const out = await req<{
    kyc: KycState;
    account: VoiceLinkAccount | null;
    redirect_url?: string;
    warning?: string;
    message?: string;
  }>("/api/telephony/kyc/action", { method: "POST", body: JSON.stringify(body) });
  invalidate("/api/telephony");
  return out;
};

export const uploadKycDocument = async (documentType: string, file: File) => {
  const form = new FormData();
  form.set("document_type", documentType);
  form.set("document", file);
  const res = await fetch(`${BASE}/api/telephony/kyc/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    throw new Error(
      (await res.json().catch(() => ({})))?.detail || "Upload failed",
    );
  }
  invalidate("/api/telephony");
  return res.json() as Promise<{ kyc: KycState; account: VoiceLinkAccount | null }>;
};

export const searchNumbers = (params: {
  type?: string;
  months?: number;
  number?: string;
  page?: number;
}) => {
  const qs = new URLSearchParams();
  qs.set("type", params.type || "3");
  qs.set("months", String(params.months || 1));
  if (params.number) qs.set("number", params.number);
  qs.set("page", String(params.page || 1));
  return req<{ items: AvailableNumber[]; total: number; page: number }>(
    `/api/telephony/numbers/search?${qs.toString()}`,
  );
};

export const quoteNumber = async (body: {
  did_id: string;
  number: string;
  months?: number;
  channels?: number;
  idempotency_key: string;
}) => {
  const out = await req<{ purchase: PhonePurchase }>("/api/telephony/numbers/quote", {
    method: "POST",
    body: JSON.stringify(body),
  });
  invalidate("/api/telephony");
  return out;
};

export const confirmPurchase = async (id: string) => {
  const out = await req<{
    purchase: PhonePurchase;
    numbers: PhoneNumberRecord[];
    wallet: TelephonyOverview["wallet"];
  }>(`/api/telephony/purchases/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ accept_auto_renew: true }),
  });
  invalidate("/api/telephony");
  invalidate("/api/wallet");
  invalidate("/api/agents");
  return out;
};

export const retryProvision = async (phoneId: string) => {
  const out = await req<{ phone_number: PhoneNumberRecord }>(
    `/api/telephony/numbers/${phoneId}/retry-provision`,
    { method: "POST" },
  );
  invalidate("/api/telephony");
  invalidate("/api/agents");
  return out;
};

export const syncInbound = async (phoneId: string) => {
  const out = await req<{ phone_number: PhoneNumberRecord }>(
    `/api/telephony/numbers/${phoneId}/sync-inbound`,
    { method: "POST" },
  );
  invalidate("/api/telephony");
  return out;
};

export const allocateCallingBalance = async (amount: number) => {
  const out = await req<{
    wallet: TelephonyOverview["wallet"];
    account: VoiceLinkAccount;
  }>("/api/telephony/wallet/allocate", {
    method: "POST",
    body: JSON.stringify({ amount, description: "Calling balance" }),
  });
  invalidate("/api/telephony");
  invalidate("/api/wallet");
  return out;
};
