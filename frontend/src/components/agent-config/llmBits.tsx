"use client";
// LLM types + small pure helpers + leaf components for the agent-config
// provider pickers (moved out of AgentConfigForm; ≤300-line rule).

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

/** Tolerate either an array or an id-keyed object from /api/catalog. */
export const asList = <T,>(v: any): T[] =>
  Array.isArray(v) ? v : v && typeof v === "object" ? (Object.values(v) as T[]) : [];

/** Find a model in the live list first, then in the full (incl. deprecated) one. */
export function getModelMeta(
  llmModels: LLMModel[], llmModelsAll: LLMModel[], provider: string, modelId: string,
): LLMModel | undefined {
  return (
    llmModels.find((m) => m.provider === provider && m.model_id === modelId) ||
    llmModelsAll.find((m) => m.provider === provider && m.model_id === modelId)
  );
}

/** Human-readable price: Sarvam bills in INR, everyone else in USD. */
export function priceLabel(m: LLMModel) {
  if ((m as any).price_inr_per_1m || m.price_currency === "INR") {
    const pin = (m as any).price_inr_per_1m;
    return pin ? `₹${pin.input}/1M in, ₹${pin.output}/1M out`
               : `₹${m.input_price_per_1m}/1M in, ₹${m.output_price_per_1m}/1M out`;
  }
  return `$${m.input_price_per_1m}/1M in, $${m.output_price_per_1m}/1M out`;
}

/**
 * Models still offered for a provider, plus the one this agent already uses
 * (even if deprecated) so the select never blanks out or silently changes it.
 */
export function modelsForSelect(
  llmByProvider: Record<string, LLMModel[]>, llmModelsAll: LLMModel[],
  provider: string, current: string,
): LLMModel[] {
  const active = llmByProvider[provider] || [];
  if (active.some((m) => m.model_id === current)) return active;
  const saved = llmModelsAll.find((m) => m.provider === provider && m.model_id === current);
  return saved ? [saved, ...active] : active;
}

/** The info card under a picked LLM model. */
export function ModelInfo({ meta }: { meta: LLMModel | undefined }) {
  if (!meta) return null;
  return (
    <div className="mt-2 p-2 bg-gray-800/50 rounded-lg border border-gray-700/50 text-[11px] space-y-1">
      <div className="flex flex-wrap gap-2">
        <span className="bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded">
          Input {meta.price_currency === "INR" ? `₹${meta.input_price_per_1m}/1M` : `$${meta.input_price_per_1m}/1M`}
        </span>
        <span className="bg-green-500/20 text-green-300 px-2 py-0.5 rounded">
          Cached {meta.price_currency === "INR" ? `₹${meta.cached_input_price_per_1m}/1M` : `$${meta.cached_input_price_per_1m}/1M`}
        </span>
        <span className="bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded">
          Output {meta.price_currency === "INR" ? `₹${meta.output_price_per_1m}/1M` : `$${meta.output_price_per_1m}/1M`}
        </span>
        {meta.free_tier && (
          <span className="bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded">free tier (rate-limited)</span>
        )}
        {meta.voice_recommended && (
          <span className="bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded">★ recommended for voice</span>
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
        {meta.cost_per_1k_output != null && (
          <span>• ${meta.cost_per_1k_output}/1K out tokens</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {meta.capabilities.map((c) => (
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
}

/**
 * Reasoning controls, shown only when the selected model accepts them.
 * (LLM temperature is intentionally NOT a user-facing control: every model
 * runs with the provider's own default sampling.)
 */
export function TuningControls({ meta, effort, onEffort }: {
  meta: LLMModel | undefined;
  effort: string;
  onEffort: (v: string) => void;
}) {
  if (!meta) return null;
  const supportsReasoning = !!(meta.reasoning_supported || meta.supports_reasoning_effort);
  if (!supportsReasoning) return null;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-400 font-medium">Reasoning effort</span>
        <select
          value={effort}
          onChange={(e) => onEffort(e.target.value)}
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
    </div>
  );
}
