"use client";

import { Brain, AlertCircle, Loader2, Save, Plus, Shield } from "lucide-react";
import { Catalog } from "@/lib/index";
import ProviderOptions from "./ProviderOptions";
import { KIND_LABEL, optionKey } from "./constants";
import {
  getModelMeta,
  modelsForSelect,
  priceLabel,
  ModelInfo,
  TuningControls,
} from "./llmBits";
import type { RightState, RightSetters } from "./columnTypes";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type { RightState, RightSetters } from "./columnTypes";

const FALLBACK_KINDS = ["llm", "stt", "tts"] as const;

// Helper: Safely resolves Edit-mode legacy DB values that might not exist in the current catalog
// ensuring shadcn Select always has a matching SelectItem to display.
function getSafeList(
  list: any[] = [],
  idKey: string,
  currentVal: string,
  nameKey: string = "display_name",
) {
  if (!currentVal) return list;
  if (list.some((item) => item[idKey] === currentVal)) return list;
  return [
    ...list,
    { [idKey]: currentVal, [nameKey]: `${currentVal} (Legacy)` },
  ];
}

export default function RightColumn({
  v,
  set,
  catalog,
}: {
  v: RightState;
  set: RightSetters;
  catalog: Catalog;
}) {
  const meta = (p: string, m: string) =>
    getModelMeta(v.llmModels, v.llmModelsAll, p, m);
  const forSelect = (p: string, cur: string) =>
    modelsForSelect(v.llmByProvider, v.llmModelsAll, p, cur);

  return (
    <div className="space-y-8">
      {/* ── SECTION 4: AI Providers & Models ── */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-foreground">
          Providers & Models
        </h3>

        {/* Primary LLM Brain */}
        {v.mode === "assistant" && v.isV2 && (
          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5 sm:p-6">
            <div className="mb-5 flex items-center gap-2">
              <Brain className="h-5 w-5 text-primary" />
              <p className="font-semibold text-primary">
                Primary Intelligence Brain
              </p>
            </div>

            <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label className="text-primary/80">Provider</Label>
                <Select
                  value={v.primaryLlmProvider || undefined}
                  onValueChange={(val) => val && set.setPrimaryLlmProvider(val)}
                >
                  <SelectTrigger className="border-primary/20 bg-background shadow-sm">
                    <SelectValue placeholder="Select provider" />
                  </SelectTrigger>
                  <SelectContent>
                    {getSafeList(
                      v.llmProviders.some((p) => p.id === v.primaryLlmProvider)
                        ? v.llmProviders
                        : [
                            ...v.llmProviders,
                            ...v.llmProvidersAll.filter(
                              (p) => p.id === v.primaryLlmProvider,
                            ),
                          ],
                      "id",
                      v.primaryLlmProvider,
                    ).map((p: any) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.display_name}{" "}
                        {p.tier === "free"
                          ? "(free)"
                          : p.tier === "freemium"
                            ? "(free tier)"
                            : p.tier
                              ? "(paid)"
                              : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-primary/80">Model</Label>
                <Select
                  value={v.primaryLlmModel || undefined}
                  onValueChange={(val) => val && set.setPrimaryLlmModel(val)}
                >
                  <SelectTrigger className="border-primary/20 bg-background shadow-sm">
                    <SelectValue placeholder="Select model" />
                  </SelectTrigger>
                  <SelectContent>
                    {getSafeList(
                      forSelect(v.primaryLlmProvider, v.primaryLlmModel),
                      "model_id",
                      v.primaryLlmModel,
                    ).map((m: any) => (
                      <SelectItem key={m.model_id} value={m.model_id}>
                        {m.display_name}{" "}
                        {m.input_price_per_1m ? `— ${priceLabel(m)}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-5 space-y-4">
              <ModelInfo meta={meta(v.primaryLlmProvider, v.primaryLlmModel)} />
              <TuningControls
                meta={meta(v.primaryLlmProvider, v.primaryLlmModel)}
                effort={v.reasoningEffort}
                onEffort={set.setReasoningEffort}
              />
            </div>
          </div>
        )}

        {/* Legacy LLM */}
        {v.mode === "assistant" && !v.isV2 && (
          <div className="rounded-2xl bg-muted/20 p-5 sm:p-6">
            <h4 className="mb-4 text-sm font-semibold">{KIND_LABEL.llm}</h4>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Provider</Label>
                <Select
                  value={v.picked.llm || undefined}
                  onValueChange={(val) => val && set.setPick("llm", val)}
                >
                  <SelectTrigger className="bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {getSafeList(
                      catalog.catalog.llm.filter(
                        (p: any) => !(p as any).legacy,
                      ),
                      "id",
                      v.picked.llm,
                    ).map((p: any) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <ProviderOptions
                provider={v.providerByName[v.picked.llm]}
                optKey={optionKey("llm", v.picked.llm)}
                optionVals={v.optionVals}
                onOption={set.onOption}
              />
            </div>
          </div>
        )}

        {/* Other Providers (STT, TTS, Telephony) */}
        {v.visibleKinds.map((kind) => (
          <div key={kind} className="rounded-2xl bg-muted/20 p-5 sm:p-6">
            <h4 className="mb-4 text-sm font-semibold">{KIND_LABEL[kind]}</h4>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Provider</Label>
                <Select
                  value={v.picked[kind] || undefined}
                  onValueChange={(val) => val && set.setPick(kind, val)}
                >
                  <SelectTrigger className="bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {getSafeList(
                      catalog.catalog[kind],
                      "id",
                      v.picked[kind],
                    ).map((p: any) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <ProviderOptions
                provider={v.providerByName[v.picked[kind]]}
                optKey={optionKey(kind, v.picked[kind])}
                optionVals={v.optionVals}
                onOption={set.onOption}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Fallbacks */}
      <div className="rounded-2xl border border-dashed border-border/80 bg-muted/10 p-5 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Shield className="h-4 w-4" />
            </div>
            <div>
              <h4 className="text-sm font-semibold">Fallback Providers</h4>
              <p className="text-[11px] text-muted-foreground">
                V2 · Multiple models
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => set.setFallbackEnabled(!v.fallbackEnabled)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold transition-colors",
              v.fallbackEnabled
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground",
            )}
          >
            {v.fallbackEnabled ? "Enabled" : "Disabled"}
          </button>
        </div>

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {v.mode === "announcement"
            ? "Announcement mode plays a fixed script — only a backup voice (TTS) applies. If the primary TTS fails, the fallback TTS speaks the script."
            : "Fallback supports multiple models with provider+model separate. Example: primary OpenAI gpt-4.1-mini, fallback Groq openai/gpt-oss-120b."}
        </p>

        {v.fallbackEnabled && (
          <div className="mt-4 space-y-4">
            {v.mode === "assistant" && v.isV2 && (
              <div className="rounded-xl border border-border/50 bg-background p-4 shadow-sm">
                <p className="mb-3 text-xs font-semibold text-muted-foreground">
                  LLM Fallback
                </p>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Provider</Label>
                    <Select
                      value={v.fallbackLlmProvider || undefined}
                      onValueChange={(val) =>
                        val && set.setFallbackLlmProvider(val)
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {getSafeList(
                          v.llmProviders,
                          "id",
                          v.fallbackLlmProvider,
                        ).map((p: any) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.display_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Model</Label>
                    <Select
                      value={v.fallbackLlmModel || undefined}
                      onValueChange={(val) =>
                        val && set.setFallbackLlmModel(val)
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {getSafeList(
                          v.llmByProvider[v.fallbackLlmProvider] || [],
                          "model_id",
                          v.fallbackLlmModel,
                        ).map((m: any) => (
                          <SelectItem key={m.model_id} value={m.model_id}>
                            {m.display_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="mt-3">
                  <ModelInfo
                    meta={meta(v.fallbackLlmProvider, v.fallbackLlmModel)}
                  />
                </div>
              </div>
            )}

            {(v.mode === "announcement"
              ? FALLBACK_KINDS.filter((k) => k === "tts")
              : FALLBACK_KINDS.filter((k) => k !== "llm" || !v.isV2)
            ).map((kind) => (
              <div
                key={kind}
                className="rounded-xl border border-border/50 bg-background p-4 shadow-sm"
              >
                <p className="mb-3 text-xs font-semibold text-muted-foreground">
                  {KIND_LABEL[kind]} Fallback
                </p>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Provider</Label>
                    <Select
                      value={v.fallbackPicked[kind] || undefined}
                      onValueChange={(val) =>
                        val && set.setFallbackPick(kind, val)
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {getSafeList(
                          catalog.catalog[kind],
                          "id",
                          v.fallbackPicked[kind],
                        ).map((p: any) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.display_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <ProviderOptions
                    provider={v.providerByName[v.fallbackPicked[kind]]}
                    optKey={optionKey(kind, v.fallbackPicked[kind], "fallback")}
                    optionVals={v.optionVals}
                    onOption={set.onOption}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Save Strip */}
      <div className="mt-8 space-y-4">
        {v.err && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{v.err}</span>
          </div>
        )}

        <Button
          onClick={set.submit}
          disabled={v.busy}
          className="h-12 w-full text-base font-bold shadow-lg shadow-primary/20"
        >
          {v.busy ? (
            <>
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Saving...
            </>
          ) : v.editing ? (
            <>
              <Save className="mr-2 h-5 w-5" />
              Save Changes
            </>
          ) : (
            <>
              <Plus className="mr-2 h-5 w-5" />
              Create Agent
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
