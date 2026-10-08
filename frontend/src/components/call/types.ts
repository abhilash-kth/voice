// Shared types/constants for the call/* components (moved from CallPanel).
import { Agent } from "@/lib/api";

export type CallState =
  | "idle"
  | "connecting"
  | "waiting_for_agent"
  | "connected"
  | "ending"
  | "ended"
  | "error";

export { type Agent };

export const STATIC_AUDIO_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

export const LAST_AGENT_KEY = "voice_agent_last_selected_id";
