// Pure form-state → API payload builders for the agent-config form
// (moved out of AgentConfigForm; no JSX, no React — unit-testable).
import { ProviderDef } from "@/lib/api";
import { getModelMeta, LLMModel } from "./llmBits";
import { optionKey } from "./constants";

/** Map a legacy provider id (e.g. groq_gpt_oss_20b) to {provider, model}. */
export function parseOldLlmId(id: string, config: any) {
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
}

/** Primary LLM provider/model from the agent being edited (V2 preferred). */
export function initPrimary(editing?: { providers?: any } | null) {
  if (editing?.providers) {
    const p: any = editing.providers;
    if (p.llm_v2?.provider && p.llm_v2?.model_id) {
      return { provider: p.llm_v2.provider, model: p.llm_v2.model_id };
    }
    if (p.llm) {
      return parseOldLlmId(p.llm.id, p.llm.config);
    }
  }
  return { provider: "openai", model: "gpt-4.1-mini" };
}

/** Fallback LLM provider/model from the agent being edited. */
export function initFallback(editing?: { providers?: any } | null) {
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
}

/** Seed the per-provider option values from the agent being edited. */
export function initOptionVals(kinds: readonly string[], editing?: { providers?: any } | null) {
  const values: Record<string, Record<string, string>> = {};
  const providers = editing?.providers as any;
  for (const kind of kinds) {
    const primary = providers?.[kind];
    if (primary?.id) values[optionKey(kind, primary.id)] = { ...(primary.config || {}) };
    const fallback = providers?.[`${kind}_fallback`];
    if (fallback?.id) values[optionKey(kind, fallback.id, "fallback")] = { ...(fallback.config || {}) };
  }
  return values;
}

/** One {id, config} provider entry, defaulting model/voice from the catalog. */
export function buildProviderEntry(
  providerByName: Record<string, ProviderDef>,
  kind: string, pid: string, role: "primary" | "fallback",
  optionVals: Record<string, Record<string, string>>,
) {
  const p = providerByName[pid];
  const opts = { ...(optionVals[optionKey(kind, pid, role)] || {}) };
  if (p?.model && !opts.model) opts.model = p.model as string;
  if (p?.voice && !opts.voice) opts.voice = p.voice as string;
  return { id: pid, config: opts };
}

/** Everything buildConfig needs — the form's assembled state. */
export interface BuildInput {
  mode: string;
  isV2: boolean;
  providerByName: Record<string, ProviderDef>;
  picked: Record<string, string>;
  fallbackPicked: Record<string, string>;
  fallbackEnabled: boolean;
  fallbackKinds: readonly string[];
  optionVals: Record<string, Record<string, string>>;
  llmModels: LLMModel[];
  llmModelsAll: LLMModel[];
  primaryLlmProvider: string;
  primaryLlmModel: string;
  fallbackLlmProvider: string;
  fallbackLlmModel: string;
  reasoningEffort: string;
}

/** Build the `providers` payload exactly as the backend expects it. */
export function buildConfig(s: BuildInput) {
  const cfg: any = {};
  const meta = (p: string, m: string) => getModelMeta(s.llmModels, s.llmModelsAll, p, m);
  const entry = (kind: string, pid: string, role: "primary" | "fallback" = "primary") =>
    buildProviderEntry(s.providerByName, kind, pid, role, s.optionVals);

  // STT, TTS, telephony (same for V2 and legacy)
  const nonLlm = () => {
    for (const kind of ["stt", "tts", "telephony"] as const) {
      const pid = s.picked[kind];
      if (!pid) continue;
      cfg[kind] = entry(kind, pid);
    }
  };

  const sttTtsFallbacks = () => {
    if (!s.fallbackEnabled) return;
    // Announcement mode has no STT/LLM at runtime — only the voice (TTS) can fall back.
    const fbKinds = s.mode === "announcement" ? (["tts"] as const) : (["stt", "tts"] as const);
    for (const kind of fbKinds) {
      const fpid = s.fallbackPicked[kind];
      if (!fpid) continue;
      if (fpid === s.picked[kind]) {
        const primaryCfg = cfg[kind]?.config || {};
        const fallbackCfg = s.optionVals[optionKey(kind, fpid, "fallback")] || {};
        const sameModel = (primaryCfg.model || "") === (fallbackCfg.model || "")
          && Object.keys(fallbackCfg).length === 0;
        if (sameModel) continue;
      }
      cfg[`${kind}_fallback`] = entry(kind, fpid, "fallback");
    }
  };

  if (!s.isV2) {
    // Legacy: LLM is a catalog provider too.
    nonLlm();
    if (s.picked.llm) cfg.llm = entry("llm", s.picked.llm);
    sttTtsFallbacks();
    if (s.fallbackEnabled) {
      const fpid = s.fallbackPicked.llm;
      if (s.mode !== "announcement" && fpid && fpid !== s.picked.llm) {
        cfg.llm_fallback = entry("llm", fpid, "fallback");
      }
    }
    return cfg;
  }

  // V2 LLM handling: provider and model stay separate; only reasoning effort
  // is user-tunable (temperature rides provider defaults).
  const primaryMeta = meta(s.primaryLlmProvider, s.primaryLlmModel);
  const tuning: any = {};
  if (primaryMeta?.reasoning_supported || primaryMeta?.supports_reasoning_effort) {
    tuning.reasoning_effort = s.reasoningEffort;
  }
  const maxTokens = primaryMeta?.max_output_tokens
    ? Math.min(80, primaryMeta.max_output_tokens)
    : 80;
  cfg.llm = {
    id: s.primaryLlmProvider,
    config: {
      model: s.primaryLlmModel,
      provider: s.primaryLlmProvider,
      base_url: primaryMeta?.base_url || "",
      max_tokens: maxTokens,
      ...tuning,
    },
  };
  cfg.llm_v2 = {
    provider: s.primaryLlmProvider,
    model_id: s.primaryLlmModel,
    base_url: primaryMeta?.base_url || "",
    max_tokens: maxTokens,
    ...tuning,
  };
  if (s.fallbackEnabled && s.mode !== "announcement") {
    const fallbackMeta = meta(s.fallbackLlmProvider, s.fallbackLlmModel);
    // Do not treat Groq 120B as OpenAI — keep separate
    if (!(s.primaryLlmProvider === s.fallbackLlmProvider && s.primaryLlmModel === s.fallbackLlmModel)) {
      const fbTuning: any = {};
      if (fallbackMeta?.reasoning_supported || fallbackMeta?.supports_reasoning_effort) {
        fbTuning.reasoning_effort = s.reasoningEffort;
      }
      cfg.llm_fallback = {
        id: s.fallbackLlmProvider,
        config: {
          model: s.fallbackLlmModel,
          provider: s.fallbackLlmProvider,
          base_url: fallbackMeta?.base_url || "",
          max_tokens: 80,
          ...fbTuning,
        },
      };
      cfg.llm_fallback_v2 = {
        provider: s.fallbackLlmProvider,
        model_id: s.fallbackLlmModel,
        base_url: fallbackMeta?.base_url || "",
        max_tokens: 80,
        ...fbTuning,
      };
    }
  }
  nonLlm();
  sttTtsFallbacks();
  return cfg;
}
