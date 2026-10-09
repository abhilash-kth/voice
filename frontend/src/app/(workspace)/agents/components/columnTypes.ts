// Prop bags shared by LeftColumn / RightColumn (kept here so the column
// files stay under the 300-line budget and this is the one import point).
import { ProviderDef } from "@/lib/api";
import { FaqItem } from "./constants";
import { LLMModel, LLMProvider } from "./llmBits";

/** Provider kinds that exist in the catalog (typed so catalog[kind] works). */
export type PickerKind = "llm" | "stt" | "tts" | "telephony";

// ---- LeftColumn -------------------------------------------------------------
export interface LeftState {
  name: string; greeting: string; fallbackResponse: string;
  noResponseTimeout: number; noResponseMessage: string;
  mode: string; announceText: string; endAfterAnnouncement: boolean;
  personality: string; language: string; gender: string;
  memoryEnabled: boolean; recordingEnabled: boolean; maxConcurrency: number;
  knowledgeText: string; systemPrompt: string; faq: FaqItem[];
  file: File | null; savedDocuments: { name: string; content: string }[];
  hasText: boolean;
  picked: Record<string, string>;
}

export interface LeftSetters {
  setName: (v: string) => void;
  setGreeting: (v: string) => void;
  setFallbackResponse: (v: string) => void;
  setNoResponseTimeout: (v: number) => void;
  setNoResponseMessage: (v: string) => void;
  setMode: (v: string) => void;
  setAnnounceText: (v: string) => void;
  setEndAfterAnnouncement: (v: boolean) => void;
  setPersonality: (v: string) => void;
  setLanguage: (v: string) => void;
  setGender: (v: string) => void;
  setMemoryEnabled: (v: boolean) => void;
  setRecordingEnabled: (v: boolean) => void;
  setMaxConcurrency: (v: number) => void;
  setKnowledgeText: (v: string) => void;
  setSystemPrompt: (v: string) => void;
  setFaq: (f: (prev: FaqItem[]) => FaqItem[]) => void;
  setFile: (f: File | null) => void;
  setSavedDocuments: (f: (prev: { name: string; content: string }[]) => { name: string; content: string }[]) => void;
}

// ---- RightColumn ------------------------------------------------------------
export interface RightState {
  mode: string;
  isV2: boolean;
  visibleKinds: readonly PickerKind[];
  fallbackEnabled: boolean;
  picked: Record<string, string>;
  fallbackPicked: Record<string, string>;
  optionVals: Record<string, Record<string, string>>;
  providerByName: Record<string, ProviderDef>;
  llmProviders: LLMProvider[];
  llmProvidersAll: LLMProvider[];
  llmModels: LLMModel[];
  llmModelsAll: LLMModel[];
  llmByProvider: Record<string, LLMModel[]>;
  primaryLlmProvider: string;
  primaryLlmModel: string;
  fallbackLlmProvider: string;
  fallbackLlmModel: string;
  reasoningEffort: string;
  err: string;
  busy: boolean;
  editing: boolean;
}

export interface RightSetters {
  setPick: (kind: string, id: string) => void;
  setFallbackPick: (kind: string, id: string) => void;
  onOption: (optKey: string, optName: string, value: string) => void;
  setFallbackEnabled: (v: boolean) => void;
  setPrimaryLlmProvider: (v: string) => void;
  setPrimaryLlmModel: (v: string) => void;
  setFallbackLlmProvider: (v: string) => void;
  setFallbackLlmModel: (v: string) => void;
  setReasoningEffort: (v: string) => void;
  submit: () => void;
}
