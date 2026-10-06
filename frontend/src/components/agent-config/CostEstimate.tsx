"use client";
import { useEffect, useRef, useState } from "react";
import { costPreview, type CostPreview } from "@/lib/api";

/**
 * Live estimate of what THIS agent configuration bills per minute:
 *   mode rate (announcement/assistant) or model costs × margin
 *   + concurrency surcharge (agent's Max concurrent)
 *   + miscellaneous fee — all set by the Super Admin.
 * Refreshes (debounced) whenever the mode/models/concurrency change.
 */
export default function CostEstimate({
  mode,
  llmId,
  sttId,
  ttsId,
  maxConcurrency,
}: {
  mode: string;
  llmId: string;
  sttId: string;
  ttsId: string;
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
  }, [mode, llmId, sttId, ttsId, maxConcurrency]);

  if (failed) {
    return <p className="text-[10px] text-gray-600">Cost estimate unavailable right now.</p>;
  }
  if (!preview) {
    return <p className="text-[10px] text-gray-600 animate-pulse">Estimating cost…</p>;
  }

  const parts: string[] = [];
  if (Number(preview.applied_flat_rate_per_min) > 0) {
    parts.push(`${mode === "announcement" ? "announcement" : "assistant"} rate ₹${Number(preview.applied_flat_rate_per_min).toFixed(2)}/min`);
  } else {
    parts.push("models cost + margin");
  }
  if (Number(preview.concurrency_addon_per_min) > 0) {
    parts.push(`concurrency +₹${Number(preview.concurrency_addon_per_min).toFixed(2)}/min`);
  }
  if (Number(preview.misc_fee_per_min) > 0) {
    parts.push(`misc +₹${Number(preview.misc_fee_per_min).toFixed(2)}/min`);
  }

  return (
    <p className="text-xs text-gray-400" title={parts.join("  •  ")}>
      Est. billing for this configuration:{" "}
      <span className="text-emerald-300 font-bold">₹{Number(preview.client_rate_per_min).toFixed(2)}/min</span>
      <span className="text-gray-500"> ({parts.join(" + ")})</span>
    </p>
  );
}
