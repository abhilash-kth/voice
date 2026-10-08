"use client";

// Agent create/edit form — state owner only; visuals live in agent-config/*
// (≤300-line rule):
//   agent-config/LeftColumn.tsx      identity, mode, voice, knowledge base
//   agent-config/RightColumn.tsx     provider pickers + fallbacks + save
//   agent-config/ProviderOptions.tsx per-provider option selects + Toggle
//   agent-config/llmBits.tsx         LLM types, model lookup + info/tuning UI
//   agent-config/payload.ts          state → API payload builders (pure)
//   agent-config/constants.ts        languages, labels, optionKey
import { useEffect, useMemo, useState } from "react";
import {
  Catalog, ProviderDef, Agent,
  addKnowledge, setKnowledge, createAgent, updateAgent,
} from "@/lib/api";
import LeftColumn, { LeftState, LeftSetters } from "./agent-config/LeftColumn";
import RightColumn, { RightState, RightSetters } from "./agent-config/RightColumn";
import { asList, LLMModel, LLMProvider, getModelMeta } from "./agent-config/llmBits";
import {
  buildConfig, initPrimary, initFallback, initOptionVals, BuildInput,
} from "./agent-config/payload";
import { optionKey, FaqItem } from "./agent-config/constants";

interface Props {
  catalog: Catalog;
  editing?: Agent | null;
  onDone: (msg: string) => void;
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
  const [reasoningEffort, setReasoningEffort] = useState<string>(
    () => (editing?.providers as any)?.llm?.config?.reasoning_effort || "low"
  );
  const [memoryEnabled, setMemoryEnabled] = useState(editing?.memory_enabled ?? true);
  const [recordingEnabled, setRecordingEnabled] = useState(editing?.recording_enabled ?? true);
  const [maxConcurrency, setMaxConcurrency] = useState(editing?.max_concurrency ?? 1);
  const [knowledgeText, setKnowledgeText] = useState(editing?.knowledge?.text || "");
  const [systemPrompt, setSystemPrompt] = useState(editing?.knowledge?.system_prompt || "");
  const [faq, setFaq] = useState<FaqItem[]>(editing?.knowledge?.faq || []);

  // V2 LLM lists (tolerant of array- or object-shaped payloads).
  const llmProviders: LLMProvider[] = asList<LLMProvider>((catalog as any).llm_providers);
  const llmModels: LLMModel[] = asList<LLMModel>((catalog as any).llm_models);
  const llmByProvider: Record<string, LLMModel[]> = (catalog as any).llm_by_provider || {};
  const llmModelsAll: LLMModel[] = asList<LLMModel>((catalog as any).llm_models_all).length
    ? asList<LLMModel>((catalog as any).llm_models_all)
    : llmModels;
  const llmProvidersAll: LLMProvider[] = [
    ...llmProviders,
    ...asList<LLMProvider>((catalog as any).llm_legacy_providers),
  ];
  const isV2 = llmProviders.length > 0 && llmModels.length > 0;

  const [primaryLlmProvider, setPrimaryLlmProvider] = useState(() => initPrimary(editing).provider);
  const [primaryLlmModel, setPrimaryLlmModel] = useState(() => initPrimary(editing).model);
  const [fallbackLlmProvider, setFallbackLlmProvider] = useState(() => initFallback(editing).provider);
  const [fallbackLlmModel, setFallbackLlmModel] = useState(() => initFallback(editing).model);

  // Snap model to the first available one when the provider changes.
  useEffect(() => {
    if (!isV2) return;
    const models = llmByProvider[primaryLlmProvider] || [];
    if (models.length > 0 && !models.find((m) => m.model_id === primaryLlmModel)) {
      setPrimaryLlmModel(models[0].model_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryLlmProvider]);

  useEffect(() => {
    if (!isV2) return;
    const models = llmByProvider[fallbackLlmProvider] || [];
    if (models.length > 0 && !models.find((m) => m.model_id === fallbackLlmModel)) {
      setFallbackLlmModel(models[0].model_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  const [optionVals, setOptionVals] = useState<Record<string, Record<string, string>>>(() => initOptionVals(kinds, editing));
  const [file, setFile] = useState<File | null>(null);
  const [savedDocuments, setSavedDocuments] = useState<{ name: string; content: string }[]>(editing?.knowledge?.documents || []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const hasText = knowledgeText.trim().length > 0;

  const providerByName = useMemo(() => {
    const m: Record<string, ProviderDef> = {};
    for (const k of kinds) for (const p of catalog.catalog[k]) m[p.id] = p;
    return m;
  }, [catalog]);  // eslint-disable-line react-hooks/exhaustive-deps

  const setPick = (kind: string, id: string) => setPicked((p) => ({ ...p, [kind]: id }));
  const setFallbackPick = (kind: string, id: string) =>
    setFallbackPickedState((p) => ({ ...p, [kind]: id }));
  const handleOption = (optKey: string, optName: string, value: string) =>
    setOptionVals((v) => ({ ...v, [optKey]: { ...(v[optKey] || {}), [optName]: value } }));

  // Follow the selected model: reasoning models have their own effort default.
  useEffect(() => {
    const meta = getModelMeta(llmModels, llmModelsAll, primaryLlmProvider, primaryLlmModel);
    if (!meta) return;
    if (meta.supports_reasoning_effort || meta.reasoning_supported) {
      setReasoningEffort(meta.reasoning_default || "low");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryLlmProvider, primaryLlmModel]);

  const buildInput: BuildInput = {
    mode, isV2, providerByName, picked, fallbackPicked, fallbackEnabled,
    fallbackKinds, optionVals, llmModels, llmModelsAll,
    primaryLlmProvider, primaryLlmModel, fallbackLlmProvider,
    fallbackLlmModel, reasoningEffort,
  };

  const buildFaq = () => faq.filter((f) => f.q.trim() && f.a.trim());

  const submit = async () => {
    setErr("");
    if (!name) return setErr("Please give the agent a name.");
    if (mode === "announcement" && !announceText.trim()) {
      return setErr("For Announcement mode, fill in the Fixed script — it is the only thing the agent will speak.");
    }
    // Validate V2 LLM provider/model
    if (isV2) {
      const primaryMeta = getModelMeta(llmModels, llmModelsAll, primaryLlmProvider, primaryLlmModel);
      if (!primaryMeta) {
        return setErr(`Invalid primary LLM: provider=${primaryLlmProvider} model=${primaryLlmModel} not found. Valid models for ${primaryLlmProvider}: ${(llmByProvider[primaryLlmProvider] || []).map((m) => m.model_id).join(", ")}`);
      }
      if (fallbackEnabled) {
        const fallbackMeta = getModelMeta(llmModels, llmModelsAll, fallbackLlmProvider, fallbackLlmModel);
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
        providers: buildConfig(buildInput),
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

  const leftState: LeftState = {
    name, greeting, fallbackResponse, noResponseTimeout, noResponseMessage,
    mode, announceText, endAfterAnnouncement, personality, language, gender,
    memoryEnabled, recordingEnabled, maxConcurrency,
    knowledgeText, systemPrompt, faq, file, savedDocuments, hasText, picked,
  };
  const leftSet: LeftSetters = {
    setName, setGreeting, setFallbackResponse, setNoResponseTimeout,
    setNoResponseMessage, setMode, setAnnounceText, setEndAfterAnnouncement,
    setPersonality, setLanguage, setGender, setMemoryEnabled, setRecordingEnabled,
    setMaxConcurrency, setKnowledgeText, setSystemPrompt, setFaq, setFile,
    setSavedDocuments,
  };
  const rightState: RightState = {
    mode, isV2,
    visibleKinds: mode === "announcement"
      ? kinds.filter((k) => k === "tts" || k === "telephony")
      : kinds.filter((k) => k !== "llm"),
    fallbackEnabled, picked, fallbackPicked, optionVals, providerByName,
    llmProviders, llmProvidersAll, llmModels, llmModelsAll, llmByProvider,
    primaryLlmProvider, primaryLlmModel, fallbackLlmProvider, fallbackLlmModel,
    reasoningEffort, err, busy, editing: !!editing,
  };
  const rightSet: RightSetters = {
    setPick, setFallbackPick, onOption: handleOption, setFallbackEnabled,
    setPrimaryLlmProvider, setPrimaryLlmModel, setFallbackLlmProvider,
    setFallbackLlmModel, setReasoningEffort, submit,
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <LeftColumn v={leftState} set={leftSet} />
      <RightColumn v={rightState} set={rightSet} catalog={catalog} />
    </div>
  );
}
