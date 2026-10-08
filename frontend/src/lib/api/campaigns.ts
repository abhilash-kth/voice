// Campaigns (bulk calling) — split from index.ts (≤300-line rule).
import { BASE, req, cachedReq, invalidate } from "./request";

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
  const res = await fetch(`${BASE}/api/campaigns`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok)
    throw new Error(
      (await res.json().catch(() => ({})))?.detail || "Campaign create failed",
    );
  invalidate("/api/campaigns");
  return res.json();
};
export const listCampaigns = () => cachedReq<{ campaigns: Campaign[] }>("/api/campaigns", 10_000);
export const getCampaign = (id: string) =>
  req<Campaign>(`/api/campaigns/${id}`);
const _mutate = async (id: string, suffix: string, method: string) => {
  const out = await req<Campaign>(`/api/campaigns/${id}${suffix}`, { method });
  invalidate("/api/campaigns");
  return out;
};
export const startCampaign = (id: string) => _mutate(id, "/start", "POST");
export const pauseCampaign = (id: string) => _mutate(id, "/pause", "POST");
export const deleteCampaign = (id: string) => _mutate(id, "", "DELETE") as unknown as Promise<void>;

