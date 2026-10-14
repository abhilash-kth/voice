import { useEffect, useMemo, useState } from "react";
import type { Agent } from "@/lib";

const LAST_AGENT_KEY = "voice_agent_last_selected_id";

type UseAgentSelectionProps = {
  agents: Agent[];
  presetAgentId?: string;
  onPresetConsumed?: () => void;
  clearCallSummary: () => void;
  clearError: () => void;
};

// Keeps agent selection and its last-used browser storage value in sync.
export default function useAgentSelection({
  agents,
  presetAgentId,
  onPresetConsumed,
  clearCallSummary,
  clearError,
}: UseAgentSelectionProps) {
  const [agentId, setAgentId] = useState("");

  // Selects the preset, saved, or first available agent.
  useEffect(() => {
    if (!agents.length) return;

    if (presetAgentId && agents.some((agent) => agent.id === presetAgentId)) {
      setAgentId(presetAgentId);
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(LAST_AGENT_KEY, presetAgentId);
        } catch {}
      }
      onPresetConsumed?.();
      return;
    }

    if (agentId && agents.some((agent) => agent.id === agentId)) return;

    let savedAgentId: string | null = null;
    if (typeof window !== "undefined") {
      try {
        savedAgentId = localStorage.getItem(LAST_AGENT_KEY);
      } catch {}
    }

    if (savedAgentId && agents.some((agent) => agent.id === savedAgentId)) {
      setAgentId(savedAgentId);
    } else {
      const fallbackId = agents[0].id;
      setAgentId(fallbackId);
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(LAST_AGENT_KEY, fallbackId);
        } catch {}
      }
    }
  }, [agents, presetAgentId, agentId, onPresetConsumed]);

  // Updates the chosen agent and clears messages from the previous selection.
  const handleAgentSelect = (newId: string) => {
    setAgentId(newId);
    clearCallSummary();
    clearError();
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem(LAST_AGENT_KEY, newId);
      } catch {}
    }
    const found = agents.find((agent) => agent.id === newId);
    if (found) {
      console.log(
        "[AGENT_SELECTED] agent_id=" +
          found.id +
          " name=" +
          found.name +
          " mode=" +
          (found.agent_mode || "assistant"),
      );
    }
  };

  // Provides the selected agent record for the setup and call flow.
  const selected = useMemo(
    () => agents.find((agent) => agent.id === agentId),
    [agents, agentId],
  );

  return { agentId, selected, handleAgentSelect };
}
