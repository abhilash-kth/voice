"use client";

import { useCallback, useEffect, useState } from "react";
import { Agent, listAgents } from "@/lib/index";
import CampaignPanel from "@/components/CampaignPanel";

export default function CampaignsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);

  const refreshAgents = useCallback(async () => {
    try {
      const a = await listAgents();
      setAgents(a.agents);
    } catch (e) {}
  }, []);

  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  return <CampaignPanel agents={agents} onChanged={refreshAgents} />;
}
