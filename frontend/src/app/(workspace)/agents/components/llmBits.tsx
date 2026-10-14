"use client";
// LLM types + small pure helpers + leaf components for the agent-config
// provider pickers (moved out of AgentConfigForm; ≤300-line rule).

import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

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
  Array.isArray(v)
    ? v
    : v && typeof v === "object"
      ? (Object.values(v) as T[])
      : [];

/** Find a model in the live list first, then in the full (incl. deprecated) one. */
export function getModelMeta(
  llmModels: LLMModel[],
  llmModelsAll: LLMModel[],
  provider: string,
  modelId: string,
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
    return pin
      ? `₹${pin.input}/1M in, ₹${pin.output}/1M out`
      : `₹${m.input_price_per_1m}/1M in, ₹${m.output_price_per_1m}/1M out`;
  }
  return `$${m.input_price_per_1m}/1M in, $${m.output_price_per_1m}/1M out`;
}

/**
 * Models still offered for a provider, plus the one this agent already uses
 * (even if deprecated) so the select never blanks out or silently changes it.
 */
export function modelsForSelect(
  llmByProvider: Record<string, LLMModel[]>,
  llmModelsAll: LLMModel[],
  provider: string,
  current: string,
): LLMModel[] {
  const active = llmByProvider[provider] || [];
  if (active.some((m) => m.model_id === current)) return active;
  const saved = llmModelsAll.find(
    (m) => m.provider === provider && m.model_id === current,
  );
  return saved ? [saved, ...active] : active;
}

/** The info card under a picked LLM model. */
export function ModelInfo({ meta }: { meta: LLMModel | undefined }) {
  if (!meta) return null;

  const isInr =
    !!(meta as any).price_inr_per_1m || meta.price_currency === "INR";
  const money = (n: number) => (isInr ? `₹${n}` : `$${n}`);

  return (
    <div className="mt-2 space-y-2.5 rounded-xl border border-border/60 bg-primary/20 p-3 text-[11px]">
      <div className="flex flex-wrap gap-1.5">
        <Badge
          variant="outline"
          className="h-5 border-blue-500/25 bg-blue-500/10 px-2 font-medium text-blue-700 dark:text-blue-400"
        >
          Input {money(meta.input_price_per_1m)}/1M
        </Badge>
        <Badge
          variant="outline"
          className="h-5 border-emerald-500/25 bg-emerald-500/10 px-2 font-medium text-emerald-700 dark:text-emerald-400"
        >
          Cached {money(meta.cached_input_price_per_1m)}/1M
        </Badge>
        <Badge
          variant="outline"
          className="h-5 border-violet-500/25 bg-violet-500/10 px-2 font-medium text-violet-700 dark:text-violet-400"
        >
          Output {money(meta.output_price_per_1m)}/1M
        </Badge>
        {meta.free_tier && (
          <Badge
            variant="outline"
            className="h-5 border-emerald-500/25 bg-emerald-500/10 px-2 font-medium text-emerald-700 dark:text-emerald-400"
          >
            free tier (rate-limited)
          </Badge>
        )}
        {meta.voice_recommended && (
          <Badge
            variant="outline"
            className="h-5 border-amber-500/25 bg-amber-500/10 px-2 font-medium text-amber-700 dark:text-amber-400"
          >
            ★ recommended for voice
          </Badge>
        )}
        {meta.status === "deprecated" && (
          <Badge
            variant="outline"
            className="h-5 border-destructive/25 bg-destructive/10 px-2 font-medium text-destructive"
          >
            deprecated — works, but switch
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-x-2 gap-y-1 text-muted-foreground">
        <span>Context {meta.context_window.toLocaleString()}</span>
        <span className="text-border">·</span>
        <span>Max out {meta.max_output_tokens.toLocaleString()}</span>
        <span className="text-border">·</span>
        <span>Speed {meta.expected_speed}</span>
        <span className="text-border">·</span>
        <span>
          Reasoning {meta.reasoning_supported ? meta.reasoning_default : "no"}
        </span>
        {meta.cost_per_1k_output != null && (
          <>
            <span className="text-border">·</span>
            <span>${meta.cost_per_1k_output}/1K out tokens</span>
          </>
        )}
      </div>

      <div className="flex flex-wrap gap-1">
        {meta.capabilities.map((c) => (
          <Badge
            key={c}
            variant="outline"
            className="h-5 border-border/60 bg-background px-1.5 text-[10px] font-normal text-muted-foreground"
          >
            {c}
          </Badge>
        ))}
        {meta.streaming_supported && (
          <Badge
            variant="outline"
            className="h-5 border-border/60 bg-background px-1.5 text-[10px] font-normal text-muted-foreground"
          >
            streaming
          </Badge>
        )}
        {meta.tool_calling_supported && (
          <Badge
            variant="outline"
            className="h-5 border-border/60 bg-background px-1.5 text-[10px] font-normal text-muted-foreground"
          >
            tools
          </Badge>
        )}
        {meta.structured_output_supported && (
          <Badge
            variant="outline"
            className="h-5 border-border/60 bg-background px-1.5 text-[10px] font-normal text-muted-foreground"
          >
            structured
          </Badge>
        )}
      </div>

      {meta.notes && (
        <p className="leading-snug text-amber-700 dark:text-amber-300/90">
          {meta.notes}
        </p>
      )}
      {meta.base_url && (
        <p className="font-mono text-[10px] text-muted-foreground">
          Base URL: {meta.base_url}
        </p>
      )}
    </div>
  );
}

/**
 * Reasoning controls, shown only when the selected model accepts them.
 * (LLM temperature is intentionally NOT a user-facing control: every model
 * runs with the provider's own default sampling.)
 */
export function TuningControls({
  meta,
  effort,
  onEffort,
}: {
  meta: LLMModel | undefined;
  effort: string;
  onEffort: (v: string) => void;
}) {
  if (!meta) return null;
  const supportsReasoning = !!(
    meta.reasoning_supported || meta.supports_reasoning_effort
  );
  if (!supportsReasoning) return null;

  const options =
    meta.reasoning_effort_options && meta.reasoning_effort_options.length
      ? meta.reasoning_effort_options
      : ["low", "medium", "high"];

  // Keep current value visible even if options list is odd in edit mode
  const safeOptions = options.includes(effort)
    ? options
    : effort
      ? [effort, ...options]
      : options;

  return (
    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label className="text-xs font-medium text-muted-foreground">
          Reasoning effort
        </Label>
        <Select
          value={effort || undefined}
          onValueChange={(val) => val && onEffort(val)}
        >
          <SelectTrigger className="h-9 bg-background">
            <SelectValue placeholder="Select effort" />
          </SelectTrigger>
          <SelectContent>
            {safeOptions.map((r) => (
              <SelectItem key={r} value={r}>
                <span className="capitalize">{r}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          low = fastest first token (recommended for live calls); high thinks
          longer and adds latency.
        </p>
      </div>
    </div>
  );
}
