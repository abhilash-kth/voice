// Pure catalog-derivation helpers for the agent form: legacy-id parsing,
// editing-state initializers and model/pricing labelling.
// Extracted from AgentConfigForm.tsx (verbatim) — no behavior change.

import { Agent } from "@/lib/api";
import { LLMModel } from "./types";

export const optionKey = (kind: string, providerId: string, role: "primary" | "fallback" = "primary") =>
  `${role}:${kind}:${providerId}`;

export const initOptionVals = (editing?: Agent | null) => {
  const values: Record<string, Record<string, string>> = {};
  const providers = editing?.providers as any;
  for (const kind of ["llm", "stt", "tts", "telephony"] as const) {
    const primary = providers?.[kind];
    if (primary?.id) values[optionKey(kind, primary.id)] = { ...(primary.config || {}) };
    const fallback = providers?.[`${kind}_fallback`];
    if (fallback?.id) values[optionKey(kind, fallback.id, "fallback")] = { ...(fallback.config || {}) };
  }
  return values;
};

// Helper to parse old id like groq_gpt_oss_20b to provider/model
export const parseOldLlmId = (id: string, config: any) => {
  if (!id) return { provider: "groq", model: "openai/gpt-oss-20b" };
  // If config has model and provider, use those
  if (config?.provider && config?.model) {
    return { provider: config.provider, model: config.model };
  }
  if (config?.model) {
    const m = config.model;
    // Detect provider from model
    if (m.includes("gpt-oss") || m.startsWith("llama") || m.startsWith("qwen") || m.startsWith("meta-llama") || m.includes("kimi") || m.includes("moonshot")) {
      return { provider: "groq", model: m };
    }
    if (m.includes("/") && !m.startsWith("openai/")) {
      // Could be openrouter
      if (id.startsWith("openrouter") || m.includes("openrouter") || m.includes("google/") || m.includes("anthropic/")) {
        return { provider: "openrouter", model: m };
      }
    }
    // Default openai
    if (m.startsWith("gpt-") || m.startsWith("o1") || m.startsWith("o3") || m.startsWith("o4")) {
      return { provider: "openai", model: m };
    }
    // Groq models
    if (m.startsWith("openai/gpt-oss")) {
      return { provider: "groq", model: m };
    }
    return { provider: "openai", model: m };
  }
  // Parse id like openai_gpt_4_1_mini
  if (id.startsWith("groq")) return { provider: "groq", model: config?.model || "openai/gpt-oss-20b" };
  if (id.startsWith("openrouter")) return { provider: "openrouter", model: config?.model || "google/gemma-3-27b-it:free" };
  if (id.startsWith("openai")) {
    // Try to map old id to new model
    const mapping: Record<string, string> = {
      "openai_gpt_4_1": "gpt-4.1",
      "openai_gpt_4_1_mini": "gpt-4.1-mini",
      "openai_gpt_4_1_nano": "gpt-4.1-nano",
      "openai_gpt_5": "gpt-5",
      "openai_gpt_5_mini": "gpt-5-mini",
      "openai_gpt_5_nano": "gpt-5-nano",
      "openai_gpt_4o": "gpt-4o",
      "openai_gpt_4o_mini": "gpt-4o-mini",
    };
    return { provider: "openai", model: mapping[id] || config?.model || "gpt-4.1-mini" };
  }
  return { provider: "groq", model: "openai/gpt-oss-20b" };
};

// Initialize primary LLM from editing
export const initPrimary = (editing?: Agent | null) => {
  if (editing?.providers) {
    const p: any = editing.providers;
    // Check V2 first
    if (p.llm_v2?.provider && p.llm_v2?.model_id) {
      return { provider: p.llm_v2.provider, model: p.llm_v2.model_id };
    }
    if (p.llm) {
      return parseOldLlmId(p.llm.id, p.llm.config);
    }
  }
  return { provider: "openai", model: "gpt-4.1-mini" };
};

export const initFallback = (editing?: Agent | null) => {
  if (editing?.providers) {
    const p: any = editing.providers;
    if (p.llm_fallback_v2?.provider && p.llm_fallback_v2?.model_id) {
      return { provider: p.llm_fallback_v2.provider, model: p.llm_fallback_v2.model_id };
    }
    if (p.llm_fallback) {
      return parseOldLlmId(p.llm_fallback.id, p.llm_fallback.config);
    }
  }
  return { provider: "groq", model: "openai/gpt-oss-20b" };
};

export const getModelMeta = (
  llmModels: LLMModel[],
  llmModelsAll: LLMModel[],
  provider: string,
  modelId: string
): LLMModel | undefined => {
  return (
    llmModels.find(m => m.provider === provider && m.model_id === modelId) ||
    llmModelsAll.find(m => m.provider === provider && m.model_id === modelId)
  );
};

// Human-readable price: Sarvam bills in INR, everyone else in USD.
export const priceLabel = (m: LLMModel) => {
  if (m.price_inr_per_1m || m.price_currency === "INR") {
    const pin = m.price_inr_per_1m;
    return pin ? `\u20B9${pin.input}/1M in, \u20B9${pin.output}/1M out`
               : `\u20B9${m.input_price_per_1m}/1M in, \u20B9${m.output_price_per_1m}/1M out`;
  }
  return `$${m.input_price_per_1m}/1M in, $${m.output_price_per_1m}/1M out`;
};

// Models still offered for a provider, plus the one this agent already uses
// (even if deprecated) so the select never blanks out or silently changes it.
export const modelsForSelect = (
  llmByProvider: Record<string, LLMModel[]>,
  llmModelsAll: LLMModel[],
  provider: string,
  current: string
): LLMModel[] => {
  const active = llmByProvider[provider] || [];
  if (active.some(m => m.model_id === current)) return active;
  const saved = llmModelsAll.find(m => m.provider === provider && m.model_id === current);
  return saved ? [saved, ...active] : active;
};
