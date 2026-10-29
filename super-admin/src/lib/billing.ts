"use client";

// Billing config client (split from lib/api.ts; file-size budget).
import { req } from "./api";

export interface BillingConfig {
    server_cost_per_min: number;              // ₹/min platform infra, part of the rate card
    min_client_price: number;                 // absolute ₹ floor per call
    profit_margin_percent: number;            // never-loss floor margin on real cost
    wallet_topup_amounts: number[];
    voice_speed_min: number;                  // legacy columns, read-only here
    voice_speed_max: number;
    voice_speed_default: number;
    // Legacy per-mode flat rates / surcharges (retired from the formula).
    announcement_price_per_min: number;
    assistant_price_per_min: number;
    misc_fee_per_min: number;
    concurrency_addons: { up_to: number; addon_per_min: number }[];
    // Monthly subscription economics (see Plans page / customer Billing).
    concurrency_line_price_per_month: number; // legacy key: ₹/month per EXTRA VoiceLink channel
    telephony_rent_per_month: number;         // ₹/month telephony/number rent
    // Per-mode minimum customer ₹/min on the rate card.
    assistant_min_per_min: number;
    announcement_min_per_min: number;
    // Enterprise minimum BILLED duration per mode (seconds; 0 = bill actual
    // duration). A shorter call still bills this many seconds.
    assistant_min_bill_seconds: number;
    announcement_min_bill_seconds: number;
    updated_at?: string;
    [k: string]: unknown;
}

export const getBilling = () => req<BillingConfig>("/api/admin/billing");
export const updateBilling = (patch: Partial<BillingConfig>) =>
    req<BillingConfig>(`/api/admin/billing`, { method: "PUT", body: JSON.stringify(patch) });

// ---- Monthly plan tiers (agent-capacity platform fee + KB packs) ----------
export interface PlanTier {
    id: string;
    kind: "capacity" | "kb_pack";
    label: string;
    units: number;                 // capacity: #agents; kb_pack: extra KB chars
    faqs: number;                  // kb_pack: extra FAQ entries
    price_per_month: number;
    enabled: boolean;
    sort_order: number;
}
export type PlanPatch = Partial<Omit<PlanTier, "id">>;
export const listPlans = () => req<{ items: PlanTier[] }>("/api/admin/plans");
export const createPlan = (body: Omit<PlanTier, "id">) =>
    req<PlanTier>("/api/admin/plans", { method: "POST", body: JSON.stringify(body) });
export const updatePlan = (id: string, patch: PlanPatch) =>
    req<PlanTier>(`/api/admin/plans/${id}`, { method: "PUT", body: JSON.stringify(patch) });
export const deletePlan = (id: string) =>
    req<void>(`/api/admin/plans/${id}`, { method: "DELETE" });

export interface SubscriptionRow {
    subscription_id?: string;
    user_id: string;
    user_name: string;
    user_email: string;
    status: string;
    agent_limit: number;
    channels: number;
    plan_channels: number;
    allocated_channels: number;
    number_channels: number;
    concurrency_lines?: number;
    telephony_rented: boolean;
    kb_extra_chars?: number;
    kb_extra_faqs?: number;
    kb_char_limit: number;
    kb_faq_limit: number;
    monthly_total: number;
    started_at?: string;
    renews_at: string;
    last_charged_at?: string;
    past_due_since?: string;
    created_at?: string;
    updated_at?: string;
}
export interface SubscriptionCreate {
    user_id: string;
    status: "active" | "past_due" | "inactive";
    agent_limit: number;
    channels: number; // plan-selected total VoiceLink channels
    telephony_rented: boolean;
    kb_extra_chars: number;
    kb_extra_faqs: number;
    monthly_total: number;
    renews_at: string;
}
export type SubscriptionPatch = Partial<Omit<SubscriptionCreate, "user_id">>;
export const listSubscriptions = () =>
    req<{ items: SubscriptionRow[] }>("/api/admin/subscriptions");
export const getAdminSubscription = (userId: string) =>
    req<SubscriptionRow>(
        `/api/admin/subscriptions/${encodeURIComponent(userId)}`,
    );
export const createSubscription = (body: SubscriptionCreate) =>
    req<SubscriptionRow>("/api/admin/subscriptions", {
        method: "POST",
        body: JSON.stringify(body),
    });
export const updateSubscription = (userId: string, patch: SubscriptionPatch) =>
    req<SubscriptionRow>(
        `/api/admin/subscriptions/${encodeURIComponent(userId)}`,
        {
            method: "PUT",
            body: JSON.stringify(patch),
        },
    );
export const deleteSubscription = (userId: string) =>
    req<void>(`/api/admin/subscriptions/${encodeURIComponent(userId)}`, {
        method: "DELETE",
    });

// ---- per-call rate preview (used by the Billing-page calculator) ----------
// Mirrors the customer /api/cost-preview response fields the UI needs.
export interface RatePreview {
    agent_mode: string;
    duration_mins: number;
    models_rate_per_min: number;   // Σ selected models' customer ₹/min (TTS-only for announcement)
    server_per_min: number;
    rate_card_per_min: number;     // models + server
    mode_min_per_min: number;      // per-mode minimum applied as floor
    applied_rate_per_min: number;  // max(rate_card, mode_min)
    floor_applied: boolean;        // true → absolute min / margin floor raised the price
    client_price_inr: number;      // rupees billed for the given duration
    your_profit_inr: number;
    is_profit: boolean;
}
export const ratePreview = (body: {
    agent_mode: "assistant" | "announcement";
    duration_seconds: number;
    llm_provider_id?: string;
    stt_provider_id?: string;
    tts_provider_id?: string;
    telephony_provider_id?: string;
}) => req<RatePreview>("/api/cost-preview", { method: "POST", body: JSON.stringify(body) });