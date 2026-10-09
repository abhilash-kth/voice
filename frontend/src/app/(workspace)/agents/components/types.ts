// Shared types + UI constants for the agent configuration form.
// Extracted from AgentConfigForm.tsx (verbatim) — no behavior change.

import { Catalog, Agent } from "@/lib/api";

// Languages the stack can transcribe and speak (Deepgram + Google + Sarvam).
export const LANGUAGES = [
  { id: "hi", label: "Hindi (Devanagari)" },
  { id: "hi-Latn", label: "Hinglish (Latin script)" },
  { id: "en", label: "English (India)" },
  { id: "mr", label: "Marathi" },
  { id: "bn", label: "Bengali" },
  { id: "ta", label: "Tamil" },
  { id: "te", label: "Telugu" },
  { id: "kn", label: "Kannada" },
  { id: "gu", label: "Gujarati" },
  { id: "ml", label: "Malayalam" },
  { id: "pa", label: "Punjabi" },
  { id: "multi", label: "Multilingual / code-mix" },
];

// What the gender choice maps to per TTS provider (see agent_builder.py).
export const GENDER_VOICE_HINT: Record<string, string> = {
  female: "Google Chirp 3: HD \u201CLeda\u201D \u00B7 Sarvam Bulbul \u201Cpriya\u201D",
  male: "Google Chirp 3: HD \u201CCharon\u201D \u00B7 Sarvam Bulbul \u201Cshubh\u201D",
  neutral: "Google Chirp 3: HD \u201CZephyr\u201D \u00B7 Sarvam Bulbul \u201Cpriya\u201D",
};

export interface Props {
  catalog: Catalog;
  editing?: Agent | null;
  onDone: (msg: string) => void;
}

export const KIND_LABEL: Record<string, string> = {
  llm: "LLM (conversation brain)",
  stt: "STT (speech → text)",
  tts: "TTS (text → speech)",
  telephony: "Telephony (call carrier)",
};

export interface FaqItem {
  q: string;
  a: string;
}

export interface LLMModel {
  provider: string;
  model_id: string;
  display_name: string;
  base_url: string;
  input_price_per_1m: number;
  cached_input_price_per_1m: number;
  output_price_per_1m: number;
  context_window: number;
  max_output_tokens: number;
  reasoning_supported: boolean;
  reasoning_default: string;
  streaming_supported: boolean;
  tool_calling_supported: boolean;
  structured_output_supported: boolean;
  expected_speed: string;
  status: string;
  capabilities: string[];
  notes: string;
  // Temperature was removed platform-wide — every model runs on the provider's
  // own default sampling. (Never re-expose this knob to users.)
  supports_reasoning_effort?: boolean;
  reasoning_effort_options?: string[];
  voice_recommended?: boolean;
  free_tier?: boolean;
  price_currency?: string;
  price_inr_per_1m?: { input: number; cached_input: number; output: number };
  cost_per_1k_input?: number;
  cost_per_1k_output?: number;
}

export interface LLMProvider {
  id: string;
  display_name: string;
  base_url: string;
  tier: string;
  key_env?: string;
  notes?: string;
  deprecated?: boolean;
}

// Tolerate either an array or an id-keyed object from /api/catalog so the
// form can never crash after a backend/shape mismatch (never iterate blindly).
export const asList = <T,>(v: any): T[] =>
  Array.isArray(v) ? v : v && typeof v === "object" ? (Object.values(v) as T[]) : [];
