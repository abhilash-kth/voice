"use client";
import { useEffect, useRef, useState } from "react";
import { costPreview, type CostPreview } from "@/lib/api";

/**
 * Live estimate of what THIS agent configuration bills per minute:
 *   your selected LLM+STT+TTS models' ₹/min prices (set per model by the
 *   Super Admin) + the platform server cost ₹/min, floored at the mode
 *   minimum; in announcement mode the models leg is TTS + telephony ₹/min.
 *   Concurrency and the agent plan itself are monthly
 *   subscription items (Billing page), not per-minute.
 * If you've configured fallback models, only the primaries are priced here;
 * a fallback leg is billed at its own rate only when it actually serves a call.
 * Refreshes (debounced) whenever the mode/models change.
 */
export default function CostEstimate({
  mode,
  llmId,
  sttId,
  ttsId,
  teleId = "",
  maxConcurrency,
}: {
  mode: string;
  llmId: string;
  sttId: string;
  ttsId: string;
  teleId?: string;
  maxConcurrency: number;
}) {
  const [preview, setPreview] = useState<CostPreview | null>(null);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      costPreview({
        agent_mode: mode,
        max_concurrency: Math.max(1, Number(maxConcurrency) || 1),
        llm_provider_id: llmId,
        stt_provider_id: sttId,
        tts_provider_id: ttsId,
        telephony_provider_id: mode === "announcement" && teleId !== "browser" ? teleId : undefined,
      })
        .then((p) => {
          setPreview(p);
          setFailed(false);
        })
        .catch(() => setFailed(true));
    }, 400);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [mode, llmId, sttId, ttsId, teleId, maxConcurrency]);

  if (failed) {
    return <p className="text-[10px] text-gray-600">Cost estimate unavailable right now.</p>;
  }
  if (!preview) {
    return <p className="text-[10px] text-gray-600 animate-pulse">Estimating cost…</p>;
  }

  const parts: string[] = [];
  if (Number(preview.models_rate_per_min) > 0) {
    parts.push(`models ₹${Number(preview.models_rate_per_min).toFixed(2)}/min`);
  }
  if (Number(preview.server_per_min) > 0) {
    parts.push(`server ₹${Number(preview.server_per_min).toFixed(2)}/min`);
  }
  if (Number(preview.applied_rate_per_min) > Number(preview.rate_card_per_min)) {
    parts.push(`${mode === "announcement" ? "announcement" : "assistant"} minimum ₹${Number(preview.mode_min_per_min).toFixed(2)}/min applies`);
  }
  if (preview.floor_applied) {
    parts.push("minimum price applied");
  }

  return (
    <p className="text-xs text-gray-400" title={parts.join("  •  ")}>
      Est. billing for this configuration:{" "}
      <span className="text-emerald-300 font-bold">₹{Number(preview.client_rate_per_min).toFixed(2)}/min</span>
      <span className="text-gray-500"> ({parts.join(" + ")})</span>
    </p>
  );
}
