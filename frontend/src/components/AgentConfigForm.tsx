"use client";

import { useMemo, useState, useEffect } from "react";
import {
  Catalog,
  ProviderDef,
  addKnowledge,
  setKnowledge,
  createAgent,
  updateAgent,
  Agent,
} from "@/lib/api";

// Languages the stack can transcribe and speak (Deepgram + Google + Sarvam).
const LANGUAGES = [
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
const GENDER_VOICE_HINT: Record<string, string> = {
  female: "Google Chirp 3: HD \u201CLeda\u201D \u00B7 Sarvam Bulbul \u201Cpriya\u201D",
  male: "Google Chirp 3: HD \u201CCharon\u201D \u00B7 Sarvam Bulbul \u201Cshubh\u201D",
  neutral: "Google Chirp 3: HD \u201CZephyr\u201D \u00B7 Sarvam Bulbul \u201Cpriya\u201D",
};

interface Props {
  catalog: Catalog;
  editing?: Agent | null;
  onDone: (msg: string) => void;
}

const KIND_LABEL: Record<string, string> = {
  llm: "LLM (conversation brain)",
  stt: "STT (speech → text)",
  tts: "TTS (text → speech)",
  telephony: "Telephony (call carrier)",
};

interface FaqItem {
  q: string;
  a: string;
}

interface LLMModel {
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
  // Added with the provider overhaul — optional so older payloads still parse.
  supports_temperature?: boolean;
  default_temperature?: number | null;
  temperature_range?: [number, number] | null;
  supports_reasoning_effort?: boolean;
  reasoning_effort_options?: string[];
  voice_recommended?: boolean;
  free_tier?: boolean;
  price_currency?: string;
  price_inr_per_1m?: { input: number; cached_input: number; output: number };
  cost_per_1k_input?: number;
  cost_per_1k_output?: number;
}

interface LLMProvider {
  id: string;
  display_name: string;
  base_url: string;
  tier: string;
  key_env?: string;
  notes?: string;
  deprecated?: boolean;
}

export default function AgentConfigForm({ catalog, editing, onDone }: Props) {
  const kinds = ["llm", "stt", "tts", "telephony"] as const;
  const fallbackKinds = ["llm", "stt", "tts"] as const;
  const [name, setName] = useState(editing?.name || "");
  const [greeting, setGreeting] = useState(editing?.greeting || "");
  const [fallbackResponse, setFallbackResponse] = useState(
    editing?.fallback_response || "Sorry, there is a temporary technical problem. Please try again shortly."
  );
  const [noResponseTimeout, setNoResponseTimeout] = useState(editing?.no_response_timeout_seconds ?? 30);
  const [noResponseMessage, setNoResponseMessage] = useState(
    editing?.no_response_message || "I did not hear a response, so I will end the call now. Thank you for calling."
  );
  const [mode, setMode] = useState(editing?.agent_mode || "assistant");
  const [announceText, setAnnounceText] = useState(editing?.announce_text || "");
  const [endAfterAnnouncement, setEndAfterAnnouncement] = useState(
    editing?.end_after_announcement ?? false
  );
  const [personality, setPersonality] = useState(editing?.voice_personality || "friendly");
  const [language, setLanguage] = useState(editing?.language || "hi");
  // Spoken-voice gender: picks the Google Chirp 3 speaker / Sarvam Bulbul speaker.
  const [gender, setGender] = useState(editing?.gender || "female");
  // Sampling controls, sent per selected model (only when the model supports them).
  const [temperature, setTemperature] = useState<number>(() => {
    const saved = (editing?.providers as any)?.llm?.config?.temperature;
    return typeof saved === "number" ? saved : 0.7;
  });
  const [reasoningEffort, setReasoningEffort] = useState<string>(
    () => (editing?.providers as any)?.llm?.config?.reasoning_effort || "low"
  );
  const [memoryEnabled, setMemoryEnabled] = useState(editing?.memory_enabled ?? true);
  const [recordingEnabled, setRecordingEnabled] = useState(editing?.recording_enabled ?? true);
  const [maxConcurrency, setMaxConcurrency] = useState(editing?.max_concurrency ?? 1);
  const [knowledgeText, setKnowledgeText] = useState(editing?.knowledge?.text || "");
  const [systemPrompt, setSystemPrompt] = useState(editing?.knowledge?.system_prompt || "");
  const [faq, setFaq] = useState<FaqItem[]>(editing?.knowledge?.faq || []);
  
  // V2 LLM state: provider → multiple models.
  // Tolerate either an array or an id-keyed object from /api/catalog so the
  // form can never crash after a backend/shape mismatch (never iterate blindly).
  const asList = <T,>(v: any): T[] =>
    Array.isArray(v) ? v : v && typeof v === "object" ? (Object.values(v) as T[]) : [];
  const llmProviders: LLMProvider[] = asList<LLMProvider>((catalog as any).llm_providers);
  const llmModels: LLMModel[] = asList<LLMModel>((catalog as any).llm_models);
  const llmByProvider: Record<string, LLMModel[]> = (catalog as any).llm_by_provider || {};
  // Includes deprecated models so an agent saved against one still renders its
  // real metadata instead of being silently switched to a different model.
  const llmModelsAll: LLMModel[] = asList<LLMModel>((catalog as any).llm_models_all).length
    ? asList<LLMModel>((catalog as any).llm_models_all)
    : llmModels;
  const llmProvidersAll: LLMProvider[] = [
    ...llmProviders,
    ...asList<LLMProvider>((catalog as any).llm_legacy_providers),
  ];
  
  const isV2 = llmProviders.length > 0 && llmModels.length > 0;
  
  // Helper to parse old id like groq_gpt_oss_20b to provider/model
  const parseOldLlmId = (id: string, config: any) => {
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
  const initPrimary = () => {
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

  const initFallback = () => {
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

  const [primaryLlmProvider, setPrimaryLlmProvider] = useState(() => initPrimary().provider);
  const [primaryLlmModel, setPrimaryLlmModel] = useState(() => initPrimary().model);
  const [fallbackLlmProvider, setFallbackLlmProvider] = useState(() => initFallback().provider);
  const [fallbackLlmModel, setFallbackLlmModel] = useState(() => initFallback().model);

  // Update models when provider changes
  useEffect(() => {
    if (!isV2) return;
    const models = llmByProvider[primaryLlmProvider] || [];
    if (models.length > 0 && !models.find(m => m.model_id === primaryLlmModel)) {
      setPrimaryLlmModel(models[0].model_id);
    }
  }, [primaryLlmProvider]);

  useEffect(() => {
    if (!isV2) return;
    const models = llmByProvider[fallbackLlmProvider] || [];
    if (models.length > 0 && !models.find(m => m.model_id === fallbackLlmModel)) {
      setFallbackLlmModel(models[0].model_id);
    }
  }, [fallbackLlmProvider]);

  const [picked, setPicked] = useState<Record<string, string>>(
    editing?.providers
      ? {
          llm: editing.providers.llm.id,
          stt: editing.providers.stt.id,
          tts: editing.providers.tts.id,
          telephony: editing.providers.telephony?.id || "browser",
        }
      : {
          llm: "groq_gpt_oss_20b",
          stt: "deepgram_nova2",
          tts: "google_wavenet_hi",
          telephony: "browser",
        }
  );
  const [fallbackPicked, setFallbackPickedState] = useState<Record<string, string>>(() => {
    const p: any = editing?.providers || {};
    return {
      llm: p.llm_fallback?.id || "openrouter_gemma_free",
      stt: p.stt_fallback?.id || "google_stt",
      tts: p.tts_fallback?.id || "google_wavenet_hi",
    };
  });
  const [fallbackEnabled, setFallbackEnabled] = useState<boolean>(() => {
    const p: any = editing?.providers || {};
    return !!(p.llm_fallback || p.stt_fallback || p.tts_fallback || p.llm_fallback_v2);
  });
  const [optionVals, setOptionVals] = useState<Record<string, Record<string, string>>>({});
  const [file, setFile] = useState<File | null>(null);
  const [savedDocuments, setSavedDocuments] = useState(editing?.knowledge?.documents || []);
  const hasText = knowledgeText.trim().length > 0;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const providerByName = useMemo(() => {
    const m: Record<string, ProviderDef> = {};
    for (const k of kinds) for (const p of catalog.catalog[k]) m[p.id] = p;
    return m;
  }, [catalog]);

  const setPick = (kind: string, id: string) => setPicked((p) => ({ ...p, [kind]: id }));
  const setFallbackPick = (kind: string, id: string) =>
    setFallbackPickedState((p) => ({ ...p, [kind]: id }));

  const buildProviderEntry = (pid: string) => {
    const p = providerByName[pid];
    const opts = { ...(optionVals[pid] || {}) };
    if (p?.model && !opts.model) opts.model = p.model as string;
    if (p?.voice && !opts.voice) opts.voice = p.voice as string;
    return { id: pid, config: opts };
  };

  const getModelMeta = (provider: string, modelId: string): LLMModel | undefined => {
    return (
      llmModels.find(m => m.provider === provider && m.model_id === modelId) ||
      llmModelsAll.find(m => m.provider === provider && m.model_id === modelId)
    );
  };

  // Human-readable price: Sarvam bills in INR, everyone else in USD.
  const priceLabel = (m: LLMModel) => {
    if (m.price_inr_per_1m || m.price_currency === "INR") {
      const pin = m.price_inr_per_1m;
      return pin ? `\u20B9${pin.input}/1M in, \u20B9${pin.output}/1M out`
                 : `\u20B9${m.input_price_per_1m}/1M in, \u20B9${m.output_price_per_1m}/1M out`;
    }
    return `$${m.input_price_per_1m}/1M in, $${m.output_price_per_1m}/1M out`;
  };

  // Models still offered for a provider, plus the one this agent already uses
  // (even if deprecated) so the select never blanks out or silently changes it.
  const modelsForSelect = (provider: string, current: string): LLMModel[] => {
    const active = llmByProvider[provider] || [];
    if (active.some(m => m.model_id === current)) return active;
    const saved = llmModelsAll.find(m => m.provider === provider && m.model_id === current);
    return saved ? [saved, ...active] : active;
  };

  const renderModelInfo = (provider: string, modelId: string) => {
    const meta = getModelMeta(provider, modelId);
    if (!meta) return null;
    return (
      <div className="mt-2 p-2 bg-gray-800/50 rounded-lg border border-gray-700/50 text-[11px] space-y-1">
        <div className="flex flex-wrap gap-2">
          <span className="bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded">
            Input {meta.price_currency === "INR" ? `\u20B9${meta.input_price_per_1m}/1M` : `$${meta.input_price_per_1m}/1M`}
          </span>
          <span className="bg-green-500/20 text-green-300 px-2 py-0.5 rounded">
            Cached {meta.price_currency === "INR" ? `\u20B9${meta.cached_input_price_per_1m}/1M` : `$${meta.cached_input_price_per_1m}/1M`}
          </span>
          <span className="bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded">
            Output {meta.price_currency === "INR" ? `\u20B9${meta.output_price_per_1m}/1M` : `$${meta.output_price_per_1m}/1M`}
          </span>
          {meta.free_tier && (
            <span className="bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded">free tier (rate-limited)</span>
          )}
          {meta.voice_recommended && (
            <span className="bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded">\u2605 recommended for voice</span>
          )}
          {meta.status === "deprecated" && (
            <span className="bg-red-500/20 text-red-300 px-2 py-0.5 rounded">deprecated — works, but switch</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2 text-gray-400">
          <span>Context {meta.context_window.toLocaleString()}</span>
          <span>• Max out {meta.max_output_tokens.toLocaleString()}</span>
          <span>• Speed {meta.expected_speed}</span>
          <span>• Reasoning {meta.reasoning_supported ? meta.reasoning_default : "no"}</span>
          <span>• Temperature {meta.supports_temperature === false ? "fixed (reasoning model)" : "adjustable"}</span>
          {meta.cost_per_1k_output != null && (
            <span>• ${meta.cost_per_1k_output}/1K out tokens</span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {meta.capabilities.map(c => (
            <span key={c} className="bg-gray-700 px-1.5 py-0.5 rounded text-[10px]">{c}</span>
          ))}
          {meta.streaming_supported && <span className="bg-gray-700 px-1.5 py-0.5 rounded text-[10px]">streaming</span>}
          {meta.tool_calling_supported && <span className="bg-gray-700 px-1.5 py-0.5 rounded text-[10px]">tools</span>}
          {meta.structured_output_supported && <span className="bg-gray-700 px-1.5 py-0.5 rounded text-[10px]">structured</span>}
        </div>
        {meta.notes && <div className="text-amber-300/80">{meta.notes}</div>}
        {meta.base_url && <div className="text-gray-500">Base URL: {meta.base_url}</div>}
      </div>
    );
  };

  // Follow the selected model: reasoning models have their own effort default and
  // reject a custom temperature, so keep the UI honest about what will be sent.
  useEffect(() => {
    const meta = getModelMeta(primaryLlmProvider, primaryLlmModel);
    if (!meta) return;
    if (meta.supports_reasoning_effort || meta.reasoning_supported) {
      setReasoningEffort(meta.reasoning_default || "low");
    }
  }, [primaryLlmProvider, primaryLlmModel]);

  // Temperature / reasoning controls, shown only when the selected model accepts
  // them. Reasoning models (gpt-5 family, o-series) have no temperature knob.
  const renderTuning = (provider: string, modelId: string) => {
    const meta = getModelMeta(provider, modelId);
    if (!meta) return null;
    const supportsTemp = meta.supports_temperature !== false;
    const supportsReasoning = !!(meta.reasoning_supported || meta.supports_reasoning_effort);
    if (!supportsTemp && !supportsReasoning) return null;
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
        {supportsTemp ? (
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400 font-medium">
              Temperature <span className="text-blue-300">{temperature.toFixed(2)}</span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              className="w-full accent-blue-500"
            />
            <span className="text-[10px] text-gray-500">
              0.3 = tight script adherence, 0.7 = natural variation, 1.0 = most creative.
              {meta.default_temperature != null ? ` Model default ${meta.default_temperature}.` : ""}
            </span>
          </label>
        ) : (
          <div className="text-[11px] text-gray-500 self-end">
            Temperature is not adjustable on this reasoning model — the provider fixes
            sampling. Use reasoning effort instead.
          </div>
        )}
        {supportsReasoning && (
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400 font-medium">Reasoning effort</span>
            <select
              value={reasoningEffort}
              onChange={(e) => setReasoningEffort(e.target.value)}
              className="input"
            >
              {(meta.reasoning_effort_options && meta.reasoning_effort_options.length
                ? meta.reasoning_effort_options
                : ["low", "medium", "high"]
              ).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <span className="text-[10px] text-gray-500">
              low = fastest first token (recommended for live calls); high thinks longer
              and adds latency.
            </span>
          </label>
        )}
      </div>
    );
  };

  const renderOptions = (pid: string) => {
    const p = providerByName[pid];
    if (!p?.options) return null;
    return Object.entries(p.options).map(([optName, optVals]) => {
      if (!optVals || optVals.length === 0) return null;
      const current = optionVals[pid]?.[optName] || optVals[0];
      return (
        <label key={optName} className="flex flex-col gap-1 text-xs">
          <span className="text-gray-400 font-medium">{optName}</span>
          <select
            className="input"
            value={current}
            onChange={(e) =>
              setOptionVals((v) => ({
                ...v,
                [pid]: { ...(v[pid] || {}), [optName]: e.target.value },
              }))
            }
          >
            {optVals.map((o) => (
              <option key={o} value={o}>
                {optName === "model" && (p as any).cost?.per_1k_in != null
                  ? `${o} — ₹${(p as any).cost.per_1k_in}/1K in · ₹${(p as any).cost.per_1k_out}/1K out`
                  : o}
              </option>
            ))}
          </select>
        </label>
      );
    });
  };

  const buildConfig = () => {
    const cfg: any = {};
    // V2 LLM handling
    if (isV2) {
      const primaryMeta = getModelMeta(primaryLlmProvider, primaryLlmModel);
      // Reasoning models (gpt-5 family, o-series) reject a custom temperature, so
      // omit it rather than send a value the API would refuse or ignore.
      const tuning: any = {};
      if (primaryMeta?.supports_temperature !== false) tuning.temperature = temperature;
      if (primaryMeta?.reasoning_supported || primaryMeta?.supports_reasoning_effort) {
        tuning.reasoning_effort = reasoningEffort;
      }
      const maxTokens = primaryMeta?.max_output_tokens
        ? Math.min(80, primaryMeta.max_output_tokens)
        : 80;
      cfg.llm = {
        id: primaryLlmProvider,
        config: {
          model: primaryLlmModel,
          provider: primaryLlmProvider,
          base_url: primaryMeta?.base_url || "",
          max_tokens: maxTokens,
          ...tuning,
        }
      };
      cfg.llm_v2 = {
        provider: primaryLlmProvider,
        model_id: primaryLlmModel,
        base_url: primaryMeta?.base_url || "",
        max_tokens: maxTokens,
        ...tuning,
      };
      if (fallbackEnabled) {
        const fallbackMeta = getModelMeta(fallbackLlmProvider, fallbackLlmModel);
        // Do not treat Groq 120B as OpenAI - keep separate
        if (!(primaryLlmProvider === fallbackLlmProvider && primaryLlmModel === fallbackLlmModel)) {
          const fbTuning: any = {};
          if (fallbackMeta?.supports_temperature !== false) fbTuning.temperature = temperature;
          if (fallbackMeta?.reasoning_supported || fallbackMeta?.supports_reasoning_effort) {
            fbTuning.reasoning_effort = reasoningEffort;
          }
          cfg.llm_fallback = {
            id: fallbackLlmProvider,
            config: {
              model: fallbackLlmModel,
              provider: fallbackLlmProvider,
              base_url: fallbackMeta?.base_url || "",
              max_tokens: 80,
              ...fbTuning,
            }
          };
          cfg.llm_fallback_v2 = {
            provider: fallbackLlmProvider,
            model_id: fallbackLlmModel,
            base_url: fallbackMeta?.base_url || "",
            max_tokens: 80,
            ...fbTuning,
          };
        }
      }
    } else {
      // Legacy fallback
      for (const kind of ["stt", "tts", "telephony"] as const) {
        const pid = picked[kind];
        if (!pid) continue;
        cfg[kind] = buildProviderEntry(pid);
      }
      // For LLM legacy
      const pid = picked.llm;
      if (pid) cfg.llm = buildProviderEntry(pid);
      if (fallbackEnabled) {
        for (const kind of fallbackKinds) {
          if (kind === "llm") continue; // handled separately
          const fpid = fallbackPicked[kind];
          if (!fpid) continue;
          const primaryId = picked[kind];
          if (fpid === primaryId) {
            const primaryCfg = cfg[kind]?.config || {};
            const fallbackCfg = optionVals[fpid] || {};
            const sameModel = (primaryCfg.model || "") === (fallbackCfg.model || "") && Object.keys(fallbackCfg).length === 0;
            if (sameModel) continue;
          }
          cfg[`${kind}_fallback`] = buildProviderEntry(fpid);
        }
        // LLM fallback legacy
        const fpid = fallbackPicked.llm;
        if (fpid && fpid !== picked.llm) {
          cfg.llm_fallback = buildProviderEntry(fpid);
        }
      }
      return cfg;
    }

    // STT, TTS, telephony (same for V2)
    for (const kind of ["stt", "tts", "telephony"] as const) {
      const pid = picked[kind];
      if (!pid) continue;
      cfg[kind] = buildProviderEntry(pid);
    }
    if (fallbackEnabled) {
      for (const kind of ["stt", "tts"] as const) {
        const fpid = fallbackPicked[kind];
        if (!fpid) continue;
        const primaryId = picked[kind];
        if (fpid === primaryId) {
          const primaryCfg = cfg[kind]?.config || {};
          const fallbackCfg = optionVals[fpid] || {};
          const sameModel = (primaryCfg.model || "") === (fallbackCfg.model || "") && Object.keys(fallbackCfg).length === 0;
          if (sameModel) continue;
        }
        cfg[`${kind}_fallback`] = buildProviderEntry(fpid);
      }
    }
    return cfg;
  };

  const buildFaq = () => faq.filter((f) => f.q.trim() && f.a.trim());

  const submit = async () => {
    setErr("");
    if (!name) return setErr("Please give the agent a name.");
    if (mode === "announcement" && !announceText.trim() && !greeting.trim()) {
      return setErr("For Announcement mode, fill in a Fixed script (or a Greeting to use as its fallback).");
    }
    // Validate V2 LLM provider/model
    if (isV2) {
      const primaryMeta = getModelMeta(primaryLlmProvider, primaryLlmModel);
      if (!primaryMeta) {
        return setErr(`Invalid primary LLM: provider=${primaryLlmProvider} model=${primaryLlmModel} not found. Valid models for ${primaryLlmProvider}: ${(llmByProvider[primaryLlmProvider] || []).map(m => m.model_id).join(", ")}`);
      }
      if (fallbackEnabled) {
        const fallbackMeta = getModelMeta(fallbackLlmProvider, fallbackLlmModel);
        if (!fallbackMeta) {
          return setErr(`Invalid fallback LLM: provider=${fallbackLlmProvider} model=${fallbackLlmModel} not found.`);
        }
        if (fallbackMeta.provider !== fallbackLlmProvider) {
          return setErr(`Fallback model ${fallbackLlmModel} belongs to ${fallbackMeta.provider}, not ${fallbackLlmProvider}. Do not treat Groq 120B as OpenAI.`);
        }
      }
    }
    setBusy(true);
    try {
      const body = {
        name,
        description: editing?.description || "Self-service agent",
        greeting,
        language,
        gender,
        voice_personality: personality,
        agent_mode: mode,
        announce_text: mode === "announcement" ? announceText : "",
        end_after_announcement: mode === "announcement" ? endAfterAnnouncement : false,
        fallback_response: fallbackResponse.trim(),
        no_response_timeout_seconds: Math.max(15, Number(noResponseTimeout) || 30),
        no_response_message: noResponseMessage.trim(),
        memory_enabled: mode === "announcement" ? false : memoryEnabled,
        recording_enabled: mode === "announcement" ? false : recordingEnabled,
        max_concurrency: Math.max(1, Number(maxConcurrency) || 1),
        providers: buildConfig(),
        enabled: true,
      };
      const agent = editing ? await updateAgent(editing.id, body) : await createAgent(body);
      if (mode === "assistant") {
        await setKnowledge(agent.id, {
          text: file ? "" : knowledgeText,
          system_prompt: systemPrompt,
          faq: buildFaq(),
          documents: file ? [] : savedDocuments,
        });
        if (file) await addKnowledge(agent.id, { file });
      }
      onDone(editing ? "Agent updated ✅" : "Agent created ✅");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const visibleKinds = mode === "announcement" ? kinds.filter((k) => k === "tts" || k === "telephony") : kinds.filter(k => k !== "llm");

  const Toggle = ({
    on,
    set,
    label,
    hint,
  }: {
    on: boolean;
    set: (v: boolean) => void;
    label: string;
    hint: string;
  }) => (
    <button
      type="button"
      onClick={() => set(!on)}
      className={`flex items-center justify-between w-full p-3 rounded-lg border text-left ${on ? "bg-blue-500/10 border-blue-500/30" : "bg-gray-800 border-gray-700"}`}
    >
      <span>
        <span className="block text-sm font-semibold">{label}</span>
        <span className="block text-[11px] text-gray-400">{hint}</span>
      </span>
      <span className={`w-10 h-6 rounded-full relative transition ${on ? "bg-blue-600" : "bg-gray-600"}`}>
        <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${on ? "left-[18px]" : "left-0.5"}`} />
      </span>
    </button>
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <div>
          <label className="text-xs text-gray-400 font-medium">Agent name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Kavya"
            className="input mt-1"
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 font-medium">Greeting</label>
          <textarea
            value={greeting}
            onChange={(e) => setGreeting(e.target.value)}
            rows={2}
            placeholder="Namaste! Main Kavya hoon..."
            className="input mt-1"
          />
          {mode === "announcement" && (
            <p className="text-[11px] text-gray-500 mt-1">Optional in Announcement mode — used only if the Fixed script below is left empty.</p>
          )}
        </div>

        <div>
          <label className="text-xs text-gray-400 font-medium">Fallback response</label>
          <textarea
            value={fallbackResponse}
            onChange={(e) => setFallbackResponse(e.target.value)}
            rows={2}
            placeholder="Please hold on, I am having a temporary issue."
            className="input mt-1"
          />
          <p className="text-[11px] text-gray-500 mt-1">Spoken when there is a temporary network, provider, or server problem.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response timeout (seconds)</label>
            <input
              type="number"
              min={15}
              value={noResponseTimeout}
              onChange={(e) => setNoResponseTimeout(Number(e.target.value))}
              className="input mt-1"
            />
            <p className="text-[11px] text-gray-500 mt-1">Recommended: 30 seconds.</p>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response closing message</label>
            <textarea
              value={noResponseMessage}
              onChange={(e) => setNoResponseMessage(e.target.value)}
              rows={2}
              className="input mt-1"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-400 font-medium">Agent mode</label>
          <div className="grid grid-cols-2 gap-2 mt-1">
            <button
              type="button"
              onClick={() => setMode("assistant")}
              className={`py-2 rounded-lg text-sm font-semibold border ${mode === "assistant" ? "bg-green-600 border-green-500" : "bg-gray-800 border-gray-700"}`}
            >
              💬 Assistant
            </button>
            <button
              type="button"
              onClick={() => setMode("announcement")}
              className={`py-2 rounded-lg text-sm font-semibold border ${mode === "announcement" ? "bg-blue-600 border-blue-500" : "bg-gray-800 border-gray-700"}`}
            >
              📢 Announcement only
            </button>
          </div>
          <p className="text-[11px] text-gray-500 mt-1">
            <b>Assistant:</b> listens + converses (uses STT + LLM + TTS).
            <br />
            <b>Announcement only:</b> plays a fixed script and hangs up — no STT, no LLM.
          </p>
        </div>

        {mode === "announcement" && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 font-medium">Fixed script (announcement)</label>
              <textarea
                value={announceText}
                onChange={(e) => setAnnounceText(e.target.value)}
                rows={3}
                placeholder="Namaste! Ye ek reminder hai..."
                className="w-full bg-gray-800 border border-blue-600/40 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <Toggle
              on={endAfterAnnouncement}
              set={setEndAfterAnnouncement}
              label="End call after announcement"
              hint="Automatically hang up when script finishes (default: keep call open)"
            />
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">Personality</label>
            <select
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              className="input mt-1"
            >
              {["friendly", "professional", "cautious", "playful", "formal"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="input mt-1"
            >
              {LANGUAGES.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] text-gray-500">
              Drives STT language and the TTS locale the agent speaks in.
            </p>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">Voice gender</label>
            <select
              value={gender}
              onChange={(e) => setGender(e.target.value)}
              className="input mt-1"
            >
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="neutral">Neutral</option>
            </select>
            <p className="mt-1 text-[10px] text-gray-500">
              {GENDER_VOICE_HINT[gender] || GENDER_VOICE_HINT.female}
            </p>
          </div>
        </div>

        {mode === "assistant" && (
          <div className="space-y-2">
            <Toggle on={memoryEnabled} set={setMemoryEnabled} label="🧠 Conversation memory" hint="Agent remembers this customer across calls" />
            <Toggle on={recordingEnabled} set={setRecordingEnabled} label="🎙️ Call recording" hint="Record the audio via LiveKit Egress" />
          </div>
        )}
        <div>
          <label className="text-xs text-gray-400 font-medium">Max concurrent calls</label>
          <input
            type="number"
            min={1}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(Number(e.target.value))}
            className="input mt-1"
          />
        </div>

        {mode === "assistant" && (
          <>
            <div>
              <label className="text-xs text-gray-400 font-medium">Knowledge base (pasted text / notes)</label>
              <textarea
                value={knowledgeText}
                disabled={!!file || savedDocuments.length > 0}
                onChange={(e) => setKnowledgeText(e.target.value)}
                rows={5}
                placeholder="Company facts, FAQs, product info..."
                className="input mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">System prompt (optional)</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={3}
                placeholder="Extra instructions for the agent..."
                className="input mt-1"
              />
            </div>

            <div className="bg-gray-800/40 rounded-xl border border-gray-800 p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-400 font-medium uppercase">FAQ (Q&A pairs)</span>
                <button onClick={() => setFaq((f) => [...f, { q: "", a: "" }])} className="text-xs text-blue-400">
                  + Add
                </button>
              </div>
              {faq.length === 0 && <p className="text-[11px] text-gray-500">No FAQs yet. Add Q&A the agent should know.</p>}
              <div className="space-y-2">
                {faq.map((item, i) => (
                  <div key={i} className="grid grid-cols-1 gap-1">
                    <input
                      value={item.q}
                      onChange={(e) => setFaq((f) => f.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)))}
                      placeholder="Question"
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                    />
                    <div className="flex gap-1">
                      <input
                        value={item.a}
                        onChange={(e) => setFaq((f) => f.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)))}
                        placeholder="Answer"
                        className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                      />
                      <button onClick={() => setFaq((f) => f.filter((_, j) => j !== i))} className="text-red-400 text-xs px-2">
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400 font-medium">Upload knowledge file (.txt/.md/.csv/.json/.pdf)</label>
              {savedDocuments.length > 0 && (
                <div className="mb-2 rounded-lg border border-blue-500/30 bg-blue-500/10 p-2 text-xs">
                  <div className="font-medium">Saved knowledge file</div>
                  {savedDocuments.map((d, i) => (
                    <div key={`${d.name}-${i}`} className="flex justify-between text-gray-300">
                      <span>{d.name}</span>
                      <button type="button" onClick={() => setSavedDocuments((docs) => docs.filter((_, j) => j !== i))} className="text-red-400">
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <input
                type="file"
                disabled={hasText}
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-400 mt-1 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-white"
              />
            </div>
          </>
        )}
      </div>

      <div className="space-y-4">
        {/* V2 LLM Provider → Multiple Models */}
        {mode === "assistant" && isV2 && (
          <div className="bg-gray-900 p-4 rounded-xl border border-gray-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold">{KIND_LABEL.llm} - V2 Provider → Models</span>
              <span className="text-[11px] text-green-400">Exact model passed to runtime</span>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-gray-400 font-medium">Provider</span>
                  <select
                    value={primaryLlmProvider}
                    onChange={(e) => setPrimaryLlmProvider(e.target.value)}
                    className="input"
                  >
                    {(llmProviders.some(p => p.id === primaryLlmProvider)
                      ? llmProviders
                      : [...llmProviders, ...(llmProvidersAll.filter(p => p.id === primaryLlmProvider))]
                    ).map((p) => (
                      <option key={p.id} value={p.id} title={`${p.display_name} - ${p.base_url || "native"} - ${p.tier}${p.notes ? "\n" + p.notes : ""}`}>
                        {p.display_name} {p.tier === "free" ? "(free)" : p.tier === "freemium" ? "(free tier)" : "(paid)"}
                        {p.key_env ? ` \u00B7 ${p.key_env}` : ""}
                        {p.deprecated ? " \u2014 legacy only" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-gray-400 font-medium">Model (for {primaryLlmProvider})</span>
                  <select
                    value={primaryLlmModel}
                    onChange={(e) => setPrimaryLlmModel(e.target.value)}
                    className="input"
                  >
                    {modelsForSelect(primaryLlmProvider, primaryLlmModel).map((m) => (
                      <option
                        key={m.model_id}
                        value={m.model_id}
                        title={`${priceLabel(m)} | cached $${m.cached_input_price_per_1m}/1M | ${(m.context_window/1000).toLocaleString()}K context | max out ${m.max_output_tokens.toLocaleString()} | speed: ${m.expected_speed} | ${m.reasoning_supported ? 'reasoning: '+m.reasoning_default : 'no reasoning'} | ${m.capabilities.join(', ')}`}
                      >
                        {m.voice_recommended ? "\u2605 " : ""}{m.display_name} \u2014 {priceLabel(m)}, {m.expected_speed}
                        {m.free_tier ? " [free tier]" : ""}
                        {m.status === "deprecated" ? " (deprecated \u2014 switch recommended)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {renderModelInfo(primaryLlmProvider, primaryLlmModel)}
              {renderTuning(primaryLlmProvider, primaryLlmModel)}
            </div>
            <p className="mt-2 text-[11px] text-amber-300/90">Provider and model remain separate. No silent substitution. If invalid, returns clear config error.</p>
          </div>
        )}

        {/* Legacy LLM fallback if V2 not available */}
        {mode === "assistant" && !isV2 && (
          <div className="bg-gray-900 p-4 rounded-xl border border-gray-800">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold">{KIND_LABEL.llm}</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-gray-400 font-medium">Provider</span>
                <select
                  value={picked.llm}
                  onChange={(e) => setPick("llm", e.target.value)}
                  className="input"
                >
                  {catalog.catalog.llm.filter((p: any) => !(p as any).legacy).map((p) => (
                    <option key={p.id} value={p.id} title={`${(p as any).models ? (p as any).models.length + ' models' : ''} ${(p as any).base_url || ''}`}>
                      {p.display_name} {p.tier === "free" ? "(free)" : "*"} {(p as any).model_count ? `(${(p as any).model_count} models)` : ''}
                    </option>
                  ))}
                </select>
              </label>
              {renderOptions(picked.llm)}
            </div>
          </div>
        )}

        {visibleKinds.map((kind) => (
          <div key={kind} className="bg-gray-900 p-4 rounded-xl border border-gray-800">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold">{KIND_LABEL[kind]}</span>
              {kind === "telephony" && <span className="text-[11px] text-gray-500">browser = free, no carrier</span>}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-gray-400 font-medium">Provider</span>
                <select
                  value={picked[kind]}
                  onChange={(e) => setPick(kind, e.target.value)}
                  className="input"
                >
                  {catalog.catalog[kind].map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name} {p.tier === "free" ? "(free)" : "*"}
                    </option>
                  ))}
                </select>
              </label>
              {renderOptions(picked[kind])}
            </div>
            {providerByName[picked[kind]]?.notes && (
              <p className="mt-2 text-[11px] text-amber-300/90 leading-snug">{providerByName[picked[kind]]!.notes}</p>
            )}
          </div>
        ))}

        {/* Fallback providers V2 */}
        <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 border-dashed">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-semibold">🔁 Fallback Providers - V2 Multiple Models</span>
            <button
              type="button"
              onClick={() => setFallbackEnabled(!fallbackEnabled)}
              className={`text-xs px-3 py-1 rounded-full border ${fallbackEnabled ? "bg-green-600 border-green-500 text-white" : "bg-gray-800 border-gray-700 text-gray-400"}`}
            >
              {fallbackEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          <p className="text-[11px] text-gray-500 mb-3">
            Fallback supports multiple models with provider+model separate. Example: primary OpenAI gpt-4.1-mini, fallback Groq openai/gpt-oss-120b. Do not treat Groq 120B as OpenAI.
          </p>
          {fallbackEnabled && (
            <div className="space-y-3">
              {isV2 && (
                <div className="bg-gray-800/50 p-3 rounded-lg border border-gray-700/50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-300">LLM fallback - Provider → Model</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="text-gray-400 font-medium">Provider</span>
                      <select
                        value={fallbackLlmProvider}
                        onChange={(e) => setFallbackLlmProvider(e.target.value)}
                        className="input"
                      >
                        {llmProviders.map((p) => (
                          <option key={p.id} value={p.id} title={`${p.display_name} - ${p.base_url}`}>
                            {p.display_name} {p.tier === "free" ? "(free)" : "(paid)"}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="text-gray-400 font-medium">Model (for {fallbackLlmProvider})</span>
                      <select
                        value={fallbackLlmModel}
                        onChange={(e) => setFallbackLlmModel(e.target.value)}
                        className="input"
                      >
                        {(llmByProvider[fallbackLlmProvider] || []).map((m) => (
                          <option 
                            key={m.model_id} 
                            value={m.model_id}
                            title={`$${m.input_price_per_1m}/1M in, $${m.cached_input_price_per_1m}/1M cached, $${m.output_price_per_1m}/1M out | ${m.context_window/1000}K context | Speed: ${m.expected_speed}`}
                          >
                            {m.display_name} - ${m.input_price_per_1m}/1M in, {m.expected_speed}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {renderModelInfo(fallbackLlmProvider, fallbackLlmModel)}
                </div>
              )}
              {fallbackKinds.filter(k => k !== "llm" || !isV2).map((kind) => (
                <div key={kind} className="bg-gray-800/50 p-3 rounded-lg border border-gray-700/50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-300">{KIND_LABEL[kind]} fallback</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="text-gray-400 font-medium">Provider</span>
                      <select
                        value={fallbackPicked[kind]}
                        onChange={(e) => setFallbackPick(kind, e.target.value)}
                        className="input"
                      >
                        {catalog.catalog[kind].map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.display_name} {p.tier === "free" ? "(free)" : "*"}
                          </option>
                        ))}
                      </select>
                    </label>
                    {renderOptions(fallbackPicked[kind])}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-gray-900 p-4 rounded-xl border border-gray-800">
          <label className="text-xs text-gray-400 font-medium">Pricing</label>
          <p className="text-[13px] text-gray-300 mt-1">
            The per-minute charge to the customer is <b>calculated automatically</b> from the provider costs (LLM + STT + TTS + telephony) plus a
            platform margin set in <code>.env</code>. Your daily margin and each call&apos;s total &amp; per-minute cost are shown in the{" "}
            <span className="text-blue-400">Wallet</span> / <span className="text-blue-400">Calls</span> tabs.
          </p>
          {isV2 && (
            <p className="text-[11px] text-gray-500 mt-2">
              V2 cost tracking: input_tokens*input_price + cached_input_tokens*cached_input_price + output_tokens*output_price. Logs provider, model, TTFT, generation_time.
            </p>
          )}
        </div>

        {err && <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">{err}</div>}

        <button
          onClick={submit}
          disabled={busy}
          className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl disabled:opacity-50"
        >
          {busy ? "Saving..." : editing ? "Save Changes" : "Create Agent"}
        </button>
      </div>
    </div>
  );
}
