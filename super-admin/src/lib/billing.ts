"use client";

// Billing config client (split from lib/api.ts; file-size budget).
import { req } from "./api";

export interface ConcurrencyTier {
  up_to: number;          // applies when agent's Max concurrent ≤ this
  addon_per_min: number;  // ₹/min added on top of the call price
}

export interface BillingConfig {
  server_cost_per_min: number;
  min_client_price: number;
  profit_margin_percent: number;
  wallet_topup_amounts: number[];
  voice_speed_min: number;
  voice_speed_max: number;
  voice_speed_default: number;
  // Per-mode flat customer price (₹/min). 0 = cost×margin (legacy behaviour).
  announcement_price_per_min: number;
  assistant_price_per_min: number;
  // Miscellaneous ₹/min added to every billed call.
  misc_fee_per_min: number;
  // Concurrency surcharges, ascending by up_to.
  concurrency_addons: ConcurrencyTier[];
  updated_at?: string;
  [k: string]: unknown;
}

export const getBilling = () => req<BillingConfig>("/api/admin/billing");
export const updateBilling = (patch: Partial<BillingConfig>) =>
  req<BillingConfig>(`/api/admin/billing`, { method: "PUT", body: JSON.stringify(patch) });
