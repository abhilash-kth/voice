// Static constants + tiny shared types for the agent-config form.

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
  female: "Google Chirp 3: HD “Leda” · Sarvam Bulbul “priya”",
  male: "Google Chirp 3: HD “Charon” · Sarvam Bulbul “shubh”",
  neutral: "Google Chirp 3: HD “Zephyr” · Sarvam Bulbul “priya”",
};

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

/** Key prefix for a provider's per-option selections (primary vs fallback). */
export const optionKey = (kind: string, providerId: string, role: "primary" | "fallback" = "primary") =>
  `${role}:${kind}:${providerId}`;
