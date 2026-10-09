"use client";
// Right column of AgentConfigForm: provider pickers, fallbacks, pricing, save.
import { Catalog } from "@/lib/api";
import ProviderOptions from "./ProviderOptions";
import { KIND_LABEL, optionKey } from "./constants";
import {
  getModelMeta, modelsForSelect, priceLabel, ModelInfo, TuningControls,
} from "./llmBits";

import type { RightState, RightSetters } from "./columnTypes";

export type { RightState, RightSetters } from "./columnTypes";

const FALLBACK_KINDS = ["llm", "stt", "tts"] as const;

export default function RightColumn({ v, set, catalog }: {
  v: RightState;
  set: RightSetters;
  catalog: Catalog;
}) {
  const meta = (p: string, m: string) => getModelMeta(v.llmModels, v.llmModelsAll, p, m);
  const forSelect = (p: string, cur: string) => modelsForSelect(v.llmByProvider, v.llmModelsAll, p, cur);

  return (
    <div className="space-y-4">
      {/* V2 LLM Provider → Multiple Models */}
      {v.mode === "assistant" && v.isV2 && (
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
                  value={v.primaryLlmProvider}
                  onChange={(e) => set.setPrimaryLlmProvider(e.target.value)}
                  className="input"
                >
                  {(v.llmProviders.some((p) => p.id === v.primaryLlmProvider)
                    ? v.llmProviders
                    : [...v.llmProviders, ...(v.llmProvidersAll.filter((p) => p.id === v.primaryLlmProvider))]
                  ).map((p) => (
                    <option key={p.id} value={p.id} title={`${p.display_name} - ${p.base_url || "native"} - ${p.tier}${p.notes ? "\n" + p.notes : ""}`}>
                      {p.display_name} {p.tier === "free" ? "(free)" : p.tier === "freemium" ? "(free tier)" : "(paid)"}
                      {p.key_env ? ` · ${p.key_env}` : ""}
                      {p.deprecated ? " — legacy only" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-gray-400 font-medium">Model (for {v.primaryLlmProvider})</span>
                <select
                  value={v.primaryLlmModel}
                  onChange={(e) => set.setPrimaryLlmModel(e.target.value)}
                  className="input"
                >
                  {forSelect(v.primaryLlmProvider, v.primaryLlmModel).map((m) => (
                    <option
                      key={m.model_id}
                      value={m.model_id}
                      title={`${priceLabel(m)} | cached $${m.cached_input_price_per_1m}/1M | ${(m.context_window / 1000).toLocaleString()}K context | max out ${m.max_output_tokens.toLocaleString()} | speed: ${m.expected_speed} | ${m.reasoning_supported ? "reasoning: " + m.reasoning_default : "no reasoning"} | ${m.capabilities.join(", ")}`}
                    >
                      {m.voice_recommended ? "★ " : ""}{m.display_name} — {priceLabel(m)}, {m.expected_speed}
                      {m.free_tier ? " [free tier]" : ""}
                      {m.status === "deprecated" ? " (deprecated — switch recommended)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <ModelInfo meta={meta(v.primaryLlmProvider, v.primaryLlmModel)} />
            <TuningControls meta={meta(v.primaryLlmProvider, v.primaryLlmModel)}
                            effort={v.reasoningEffort} onEffort={set.setReasoningEffort} />
          </div>
          <p className="mt-2 text-[11px] text-amber-300/90">Provider and model remain separate. No silent substitution. If invalid, returns clear config error.</p>
        </div>
      )}

      {/* Legacy LLM fallback if V2 not available */}
      {v.mode === "assistant" && !v.isV2 && (
        <div className="bg-gray-900 p-4 rounded-xl border border-gray-800">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold">{KIND_LABEL.llm}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-400 font-medium">Provider</span>
              <select
                value={v.picked.llm}
                onChange={(e) => set.setPick("llm", e.target.value)}
                className="input"
              >
                {catalog.catalog.llm.filter((p: any) => !(p as any).legacy).map((p) => (
                  <option key={p.id} value={p.id} title={`${(p as any).models ? (p as any).models.length + " models" : ""} ${(p as any).base_url || ""}`}>
                    {p.display_name} {p.tier === "free" ? "(free)" : "*"} {(p as any).model_count ? `(${(p as any).model_count} models)` : ""}
                  </option>
                ))}
              </select>
            </label>
            <ProviderOptions provider={v.providerByName[v.picked.llm]} optKey={optionKey("llm", v.picked.llm)}
                             optionVals={v.optionVals} onOption={set.onOption} />
          </div>
        </div>
      )}

      {v.visibleKinds.map((kind) => (
        <div key={kind} className="bg-gray-900 p-4 rounded-xl border border-gray-800">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold">{KIND_LABEL[kind]}</span>
            {kind === "telephony" && <span className="text-[11px] text-gray-500">browser = free, no carrier</span>}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-400 font-medium">Provider</span>
              <select
                value={v.picked[kind]}
                onChange={(e) => set.setPick(kind, e.target.value)}
                className="input"
              >
                {catalog.catalog[kind].map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name} {p.tier === "free" ? "(free)" : "*"}
                  </option>
                ))}
              </select>
            </label>
            <ProviderOptions provider={v.providerByName[v.picked[kind]]} optKey={optionKey(kind, v.picked[kind])}
                             optionVals={v.optionVals} onOption={set.onOption} />
          </div>
          {v.providerByName[v.picked[kind]]?.notes && (
            <p className="mt-2 text-[11px] text-amber-300/90 leading-snug">{v.providerByName[v.picked[kind]]!.notes}</p>
          )}
        </div>
      ))}

      {/* Fallback providers V2 */}
      <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 border-dashed">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold">🔁 Fallback Providers - V2 Multiple Models</span>
          <button
            type="button"
            onClick={() => set.setFallbackEnabled(!v.fallbackEnabled)}
            className={`text-xs px-3 py-1 rounded-full border ${v.fallbackEnabled ? "bg-green-600 border-green-500 text-white" : "bg-gray-800 border-gray-700 text-gray-400"}`}
          >
            {v.fallbackEnabled ? "Enabled" : "Disabled"}
          </button>
        </div>
        <p className="text-[11px] text-gray-500 mb-3">
          {v.mode === "announcement"
            ? "Announcement mode plays a fixed script — only a backup voice (TTS) applies. If the primary TTS fails, the fallback TTS speaks the script."
            : "Fallback supports multiple models with provider+model separate. Example: primary OpenAI gpt-4.1-mini, fallback Groq openai/gpt-oss-120b. Do not treat Groq 120B as OpenAI."}
        </p>
        {v.fallbackEnabled && (
          <div className="space-y-3">
            {v.mode === "assistant" && v.isV2 && (
              <div className="bg-gray-800/50 p-3 rounded-lg border border-gray-700/50">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-300">LLM fallback - Provider → Model</span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1 text-xs">
                    <span className="text-gray-400 font-medium">Provider</span>
                    <select
                      value={v.fallbackLlmProvider}
                      onChange={(e) => set.setFallbackLlmProvider(e.target.value)}
                      className="input"
                    >
                      {v.llmProviders.map((p) => (
                        <option key={p.id} value={p.id} title={`${p.display_name} - ${p.base_url}`}>
                          {p.display_name} {p.tier === "free" ? "(free)" : "(paid)"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs">
                    <span className="text-gray-400 font-medium">Model (for {v.fallbackLlmProvider})</span>
                    <select
                      value={v.fallbackLlmModel}
                      onChange={(e) => set.setFallbackLlmModel(e.target.value)}
                      className="input"
                    >
                      {(v.llmByProvider[v.fallbackLlmProvider] || []).map((m) => (
                        <option
                          key={m.model_id}
                          value={m.model_id}
                          title={`$${m.input_price_per_1m}/1M in, $${m.cached_input_price_per_1m}/1M cached, $${m.output_price_per_1m}/1M out | ${m.context_window / 1000}K context | Speed: ${m.expected_speed}`}
                        >
                          {m.display_name} - ${m.input_price_per_1m}/1M in, {m.expected_speed}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <ModelInfo meta={meta(v.fallbackLlmProvider, v.fallbackLlmModel)} />
              </div>
            )}
            {(v.mode === "announcement"
              ? FALLBACK_KINDS.filter((k) => k === "tts")
              : FALLBACK_KINDS.filter((k) => k !== "llm" || !v.isV2)
            ).map((kind) => (
              <div key={kind} className="bg-gray-800/50 p-3 rounded-lg border border-gray-700/50">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-300">{KIND_LABEL[kind]} fallback</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1 text-xs">
                    <span className="text-gray-400 font-medium">Provider</span>
                    <select
                      value={v.fallbackPicked[kind]}
                      onChange={(e) => set.setFallbackPick(kind, e.target.value)}
                      className="input"
                    >
                      {catalog.catalog[kind].map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name} {p.tier === "free" ? "(free)" : "*"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <ProviderOptions provider={v.providerByName[v.fallbackPicked[kind]]}
                                   optKey={optionKey(kind, v.fallbackPicked[kind], "fallback")}
                                   optionVals={v.optionVals} onOption={set.onOption} />
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
        {v.isV2 && (
          <p className="text-[11px] text-gray-500 mt-2">
            V2 cost tracking: input_tokens*input_price + cached_input_tokens*cached_input_price + output_tokens*output_price. Logs provider, model, TTFT, generation_time.
          </p>
        )}
      </div>

      {v.err && <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">{v.err}</div>}

      <button
        onClick={set.submit}
        disabled={v.busy}
        className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl disabled:opacity-50"
      >
        {v.busy ? "Saving..." : v.editing ? "Save Changes" : "Create Agent"}
      </button>
    </div>
  );
}
