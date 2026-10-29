import { cachedReq, invalidate, req } from "./request";


export interface Entitlement {
  status: string;               // active | past_due | inactive
  agent_limit: number;
  channels: number;             // effective purchased/allocated channels
  plan_channels: number;        // total selected with the monthly plan
  allocated_channels: number;   // VoiceLink client allocation
  number_channels: number;      // highest active DID channel count
  concurrency_lines?: number;   // legacy alias returned by older backends
  telephony_rented: boolean;
  kb_char_limit: number;
  kb_faq_limit: number;
  monthly_total: number;
  renews_at: string;
  past_due_since: string;
  plan_label: string;
}

export interface PlanOption {
  id: string;
  kind: "capacity" | "kb_pack";
  label: string;
  units: number;
  faqs: number;
  price_per_month: number;
  enabled: boolean;
  sort_order: number;
}

export interface SubscriptionInfo {
  entitlement: Entitlement;
  prices: {
    channel_price_per_month: number;
    line_price_per_month?: number;
    telephony_rent_per_month: number;
  };
  plans: { capacity: PlanOption[]; kb_packs: PlanOption[] };
  base_limits: {
    kb_chars: number;
    faqs: number;
    channels: number;
    concurrency_lines?: number;
  };
}

export const getSubscription = () => cachedReq<SubscriptionInfo>("/api/subscription", 10_000);

export const purchaseSubscription = async (body: {
  capacity_tier_id?: string;
  channels?: number;
  extra_channels?: number;
  extra_lines?: number;
  telephony?: boolean;
  kb_pack_ids?: string[];
}) => {
  const out = await req<{ ok: boolean; entitlement: Entitlement }>("/api/subscription/purchase", {
    method: "POST",
    body: JSON.stringify(body),
  });
  invalidate("/api/subscription");
  invalidate("/api/wallet");
  return out;
};