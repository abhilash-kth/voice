"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listModels, type CatalogModel } from "@/lib/api";
import { ratePreview, type RatePreview } from "@/lib/billing";
import { fmtINR } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ModelLists = {
  llm: CatalogModel[];
  stt: CatalogModel[];
  tts: CatalogModel[];
  telephony: CatalogModel[];
};

export default function RateCalculator() {
  const [models, setModels] = useState<ModelLists>({
    llm: [],
    stt: [],
    tts: [],
    telephony: [],
  });
  const [mode, setMode] = useState<"assistant" | "announcement">("assistant");
  const [duration, setDuration] = useState(60);
  const [llmId, setLlmId] = useState("");
  const [sttId, setSttId] = useState("");
  const [ttsId, setTtsId] = useState("");
  const [teleId, setTeleId] = useState("");
  const [out, setOut] = useState<RatePreview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const requestSequence = useRef(0);

  useEffect(() => {
    Promise.all([
      listModels({ kind: "llm", page_size: 200 }),
      listModels({ kind: "stt", page_size: 200 }),
      listModels({ kind: "tts", page_size: 200 }),
      listModels({ kind: "telephony", page_size: 200 }),
    ])
      .then(([llmResult, sttResult, ttsResult, telephonyResult]) => {
        const live = (items: CatalogModel[]) =>
          items.filter((model) => model.enabled && model.status === "live");
        const firstLiveId = (items: CatalogModel[]) =>
          live(items)[0]?.catalog_id || "";

        setModels({
          llm: live(llmResult.items),
          stt: live(sttResult.items),
          tts: live(ttsResult.items),
          telephony: live(telephonyResult.items),
        });
        setLlmId(firstLiveId(llmResult.items));
        setSttId(firstLiveId(sttResult.items));
        setTtsId(firstLiveId(ttsResult.items));
        setTeleId(firstLiveId(telephonyResult.items));
      })
      .catch((e) => setErr((e as Error).message));
  }, []);

  const compute = useCallback(async () => {
    const currentRequest = ++requestSequence.current;
    setBusy(true);
    setErr("");

    try {
      const result = await ratePreview({
        agent_mode: mode,
        duration_seconds: Math.max(1, duration),
        llm_provider_id: llmId || undefined,
        stt_provider_id: sttId || undefined,
        tts_provider_id: ttsId || undefined,
        // Browser telephony is free; don't include it in the announcement rate.
        telephony_provider_id:
          mode === "announcement" && teleId !== "browser"
            ? teleId || undefined
            : undefined,
      });

      if (requestSequence.current === currentRequest) {
        setOut(result);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      if (requestSequence.current === currentRequest) {
        setBusy(false);
      }
    }
  }, [mode, duration, llmId, sttId, ttsId, teleId]);

  useEffect(() => {
    const timer = window.setTimeout(compute, 250);
    return () => window.clearTimeout(timer);
  }, [compute]);

  const priceOf = (list: CatalogModel[], id: string) =>
    list.find((model) => model.catalog_id === id);

  const selectedTelephony =
    teleId && teleId !== "browser"
      ? priceOf(models.telephony, teleId)
      : undefined;

  return (
    <Card className="mt-4 border-border/60 shadow-sm">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold">
            Pricing calculator
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">
            Uses current billing settings and live model prices
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 pt-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Call mode">
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                size="sm"
                variant={mode === "assistant" ? "default" : "outline"}
                onClick={() => setMode("assistant")}
              >
                Assistant
              </Button>
              <Button
                type="button"
                size="sm"
                variant={mode === "announcement" ? "default" : "outline"}
                onClick={() => setMode("announcement")}
              >
                Announcement
              </Button>
            </div>
          </Field>

          <Field label="Call duration (seconds)">
            <Input
              className="h-9 tabular-nums"
              type="number"
              min="1"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value) || 60)}
            />
          </Field>

          {mode === "assistant" ? (
            <>
              <ModelSelect
                label="LLM (talks)"
                models={models.llm}
                value={llmId}
                onChange={setLlmId}
              />
              <ModelSelect
                label="STT (listens)"
                models={models.stt}
                value={sttId}
                onChange={setSttId}
              />
            </>
          ) : (
            <div className="flex items-center rounded-lg border border-border/60 bg-muted/20 p-3 text-xs text-muted-foreground sm:col-span-2 lg:col-span-1">
              Announcements use a fixed script: the rate is TTS + paid telephony
              + server. LLM and STT are not used; browser telephony is not
              charged.
            </div>
          )}

          <ModelSelect
            label={
              mode === "announcement"
                ? "TTS (speaks the script)"
                : "TTS (speaks)"
            }
            models={models.tts}
            value={ttsId}
            onChange={setTtsId}
          />

          {mode === "announcement" && (
            <ModelSelect
              label="Telephony (phone network)"
              models={models.telephony}
              value={teleId}
              onChange={setTeleId}
            />
          )}
        </div>

        {err && (
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {err}
          </div>
        )}

        {out && !err && (
          <div className="rounded-lg border border-border/60 bg-muted/20 p-4">
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-xs">
              {mode === "assistant" && (
                <>
                  <Part
                    label={priceOf(models.llm, llmId)?.display_name || "LLM"}
                    value={
                      priceOf(models.llm, llmId)?.customer_price_per_min ?? 0
                    }
                  />
                  <Part
                    label={priceOf(models.stt, sttId)?.display_name || "STT"}
                    value={
                      priceOf(models.stt, sttId)?.customer_price_per_min ?? 0
                    }
                  />
                </>
              )}

              {mode === "announcement" && selectedTelephony && (
                <Part
                  label={selectedTelephony.display_name}
                  value={selectedTelephony.customer_price_per_min}
                />
              )}

              <Part
                label={priceOf(models.tts, ttsId)?.display_name || "TTS"}
                value={priceOf(models.tts, ttsId)?.customer_price_per_min ?? 0}
              />
              <Part label="+ server" value={out.server_per_min} />

              <span className="text-muted-foreground">=</span>
              <span className="text-foreground">
                Rate card <b>{fmtINR(out.rate_card_per_min)}/min</b>
              </span>

              {out.applied_rate_per_min > out.rate_card_per_min && (
                <span className="text-amber-700 dark:text-amber-400">
                  {mode === "announcement" ? "Announcement" : "Assistant"}{" "}
                  minimum {fmtINR(out.mode_min_per_min)}/min applies
                </span>
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
              <span className="text-sm">
                <b
                  className={
                    busy
                      ? "text-muted-foreground"
                      : "text-emerald-700 dark:text-emerald-400"
                  }
                >
                  {fmtINR(out.applied_rate_per_min)}/min · {duration}s call
                  bills {fmtINR(out.client_price_inr)}
                </b>
                {out.floor_applied && (
                  <span className="ml-2 text-[10px] text-amber-700 dark:text-amber-400">
                    (safety floor applied)
                  </span>
                )}
              </span>

              <span
                className={`text-[10px] ${
                  out.is_profit
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-destructive"
                }`}
              >
                Your profit ≈ {fmtINR(out.your_profit_inr)}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function ModelSelect({
  label,
  models,
  value,
  onChange,
}: {
  label: string;
  models: CatalogModel[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <select
        className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {models.length === 0 ? (
          <option value="">— none live —</option>
        ) : (
          models.map((model) => (
            <option key={model.catalog_id} value={model.catalog_id}>
              {model.display_name} — {fmtINR(model.customer_price_per_min)}/min
            </option>
          ))
        )}
      </select>
    </Field>
  );
}

function Part({ label, value }: { label: string; value: number }) {
  return (
    <span className="text-muted-foreground">
      <b className="text-foreground">{fmtINR(value || 0)}</b>{" "}
      <span>{label}</span>
    </span>
  );
}
