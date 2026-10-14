"use client";

import { useCallback, useEffect, useState } from "react";
import { Agent, listAgents } from "@/lib";
import CreateCampaignForm from "../components/CreateCampaignForm";

export default function NewCampaignPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const refreshAgents = useCallback(async () => {
    try {
      const result = await listAgents();
      setAgents(result.agents);
    } catch {
      // Preserve the existing behavior: agent-load failures leave the list empty.
    }
  }, []);

  useEffect(() => { void refreshAgents(); }, [refreshAgents]);

  return <CreateCampaignForm agents={agents} onChanged={refreshAgents} />;
}
