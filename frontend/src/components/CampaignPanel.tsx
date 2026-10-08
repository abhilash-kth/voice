"use client";

// Bulk-call Campaigns tab — visuals live in ./campaigns/* (≤300-line rule):
//   campaigns/CreateForm.tsx    lead-file upload + campaign settings form
//   campaigns/CampaignCard.tsx  one campaign card (+ lead table, stats)
// This panel owns the data: list refresh, the open-campaign poller, and
// all campaign API actions; the children are purely presentational.
import { useCallback, useEffect, useState } from "react";
import {
  Agent, Campaign,
  createCampaign, listCampaigns, startCampaign, pauseCampaign,
  deleteCampaign, getCampaign,
} from "@/lib/api";
import CreateForm from "./campaigns/CreateForm";
import CampaignCard from "./campaigns/CampaignCard";

export default function CampaignPanel({
  agents,
  onChanged,
}: {
  agents: Agent[];
  onChanged?: () => void;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [active, setActive] = useState<Campaign | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await listCampaigns();
      setCampaigns(res.campaigns);
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll the open campaign detail so per-lead status updates live.
  useEffect(() => {
    if (!campaignId) return;
    const iv = setInterval(async () => {
      try {
        setActive(await getCampaign(campaignId));
      } catch {
        /* ignore transient polling errors */
      }
    }, 2500);
    return () => clearInterval(iv);
  }, [campaignId]);

  const open = async (id: string) => {
    setCampaignId(id);
    try {
      setActive(await getCampaign(id));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  /** Used by CreateForm: returns null on success or an error string. */
  const createFromForm = async (form: FormData): Promise<string | null> => {
    try {
      const c = await createCampaign(form);
      await load();
      onChanged?.();
      await open(c.id);
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  };

  const act = async (id: string, action: "start" | "pause") => {
    try {
      if (action === "start") await startCampaign(id);
      else await pauseCampaign(id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this campaign and its lead list?")) return;
    try {
      await deleteCampaign(id);
      if (campaignId === id) {
        setCampaignId("");
        setActive(null);
      }
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  // The live-open campaign floats to the top so polling updates stay visible.
  const topCard: Campaign[] = active
    ? [active, ...campaigns.filter((c) => c.id !== active.id)]
    : campaigns;

  return (
    <div className="space-y-6">
      {err && (
        <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          {err}
        </div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CreateForm agents={agents} onSubmit={createFromForm} />

        {/* Right: list */}
        <div className="space-y-4">
          <h2 className="text-xl font-bold">Your Campaigns</h2>
          {topCard.length === 0 && (
            <div className="bg-gray-900 rounded-2xl border border-dashed border-gray-800 p-12 text-center">
              <div className="w-14 h-14 rounded-2xl bg-gray-800 flex items-center justify-center text-2xl mx-auto mb-4">📣</div>
              <p className="text-sm font-semibold text-gray-300">No campaigns yet</p>
              <p className="text-xs text-gray-500 mt-1 max-w-[260px] mx-auto leading-relaxed">
                Upload a lead file on the left and your agent will start
                dialling automatically.
              </p>
            </div>
          )}
          {topCard.map((c) => (
            <CampaignCard
              key={c.id}
              campaign={c}
              isOpen={active?.id === c.id}
              onToggleOpen={() => (active?.id === c.id ? setCampaignId("") : open(c.id))}
              onAction={(act2) => act(c.id, act2)}
              onDelete={() => remove(c.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
