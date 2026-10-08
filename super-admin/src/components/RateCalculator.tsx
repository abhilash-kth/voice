"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { listModels, type CatalogModel } from "@/lib/api";
import { ratePreview, type RatePreview } from "@/lib/billing";
import { fmtINR } from "@/lib/format";

/**
 * Enterprise pricing calculator — answers "if a customer picks these models,
 * what exactly bills?". Pick a call mode + duration + models; shows the rate
 * card composition (per model, from the Models page), the server component,
 * the per-mode minimum floor and the final ₹ for that call.
 *
 * Announcement mode plays a fixed script: only TTS runs, so only the TTS
 * price (+server) can bill — the LLM/STT selectors hide automatically.
 */
export default function RateCalculator() {
  const [models, setModels] = useState<{ llm: CatalogModel[]; stt: CatalogModel[]; tts: CatalogModel[] }>({
    llm: [], stt: [], tts: [],
  });
  const [mode, setMode] = useState<"assistant" | "announcement">("assistant");
  const [duration, setDuration] = useState(60);
  const [llmId, setLlmId] = useState("");
  const [sttId, setSttId] = useState("");
  const [ttsId, setTtsId] = useState("");
  const [out, setOut] = useState<RatePreview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    Promise.all([
      listModels({ kind: "llm", page_size: 200 }),
      listModels({ kind: "stt", page_size: 200 }),
      listModels({ kind: "tts", page_size: 200 }),
    ]).then(([l, s, t]) => {
      const live = (xs: CatalogModel[]) => xs.filter((m) => m.enabled && m.status === "live");
      const pick = (xs: CatalogModel[]) => (live(xs)[0]?.catalog_id || "");
      const loaded = { llm: live(l.items), stt: live(s.items), tts: live(t.items) };
      setModels(loaded);
      setLlmId(pick(l.items));
      setSttId(pick(s.items));
      setTtsId(pick(t.items));
    }).catch((e) => setErr(e.message));
  }, []);

  const compute = useCallback(async () => {
    const my = ++seq.current;
    setBusy(true);
    setErr("");
    try {
      const res = await ratePreview({
        agent_mode: mode, duration_seconds: Math.max(1, duration),
        llm_provider_id: llmId || undefined, stt_provider_id: sttId || undefined,
        tts_provider_id: ttsId || undefined,
      });
      if (seq.current === my) setOut(res);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      if (seq.current === my) setBusy(false);
    }
  }, [mode, duration, llmId, sttId, ttsId]);

  useEffect(() => {
    const t = setTimeout(compute, 250);   // debounce rapid edits
    return () => clearTimeout(t);
  }, [compute]);

  const priceOf = (list: CatalogModel[], id: string) =>
    list.find((m) => m.catalog_id === id);

  return (
    <div className="card p-5 space-y-4 mt-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold">Pricing calculator</h2>
        <span className="text-[10px] text-gray-600">live numbers from the current Billing config + Models page prices</span>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Call mode</span>
          <div className="mt-1 grid grid-cols-2 gap-1">
            {(["assistant", "announcement"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`text-xs py-2 rounded-lg border transition-colors ${mode === m
                  ? "bg-blue-600 border-blue-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"}`}>
                {m === "assistant" ? "Assistant" : "Announcement"}
              </button>
            ))}
          </div>
        </label>
        <Field label="Call duration (seconds)">
          <input className="input" type="number" min={1} value={duration}
                 onChange={(e) => setDuration(Number(e.target.value) || 60)} />
        </Field>
        {mode === "assistant" ? (
          <>
            <Sel label="LLM (talks)" list={models.llm} value={llmId} onChange={setLlmId} />
            <Sel label="STT (listens)" list={models.stt} value={sttId} onChange={setSttId} />
          </>
        ) : (
          <div className="sm:col-span-2 rounded-xl bg-gray-800/50 border border-gray-800 p-3 text-xs text-gray-400 flex items-center">
            Announcements play a fixed script — <b className="text-gray-200 mx-1">only TTS runs</b>, so
            only the TTS price + server cost can bill.
          </div>
        )}
        <Sel label={mode === "announcement" ? "TTS (speaks the script)" : "TTS (speaks)"}
             list={models.tts} value={ttsId} onChange={setTtsId} />
      </div>

      {err && <div className="text-xs text-red-300">{err}</div>}
      {out && !err && (
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-xs">
            {mode === "assistant" && (
              <>
                <Part label={priceOf(models.llm, llmId)?.display_name || "LLM"} value={priceOf(models.llm, llmId)?.customer_price_per_min ?? 0} />
                <Part label={priceOf(models.stt, sttId)?.display_name || "STT"} value={priceOf(models.stt, sttId)?.customer_price_per_min ?? 0} />
              </>
            )}
            <Part label={priceOf(models.tts, ttsId)?.display_name || "TTS"} value={priceOf(models.tts, ttsId)?.customer_price_per_min ?? 0} />
            <Part label="+ server" value={out.server_per_min} />
            <span className="text-gray-600">=</span>
            <span className="text-gray-300">
              rate card <b>{fmtINR(out.rate_card_per_min)}/min</b>
            </span>
            {out.applied_rate_per_min > out.rate_card_per_min && (
              <span className="text-amber-300">
                → {mode === "announcement" ? "announcement" : "assistant"} minimum {fmtINR(out.mode_min_per_min)}/min applies
              </span>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-gray-800 pt-3">
            <span className="text-sm">
              <b className={busy ? "text-gray-500" : "text-emerald-300"}>
                ₹{fmtINR(out.applied_rate_per_min)}/min · {duration}s call bills {fmtINR(out.client_price_inr)}
              </b>
              {out.floor_applied && (
                <span className="ml-2 text-[10px] text-amber-300/90">
                  (floor applied: absolute minimum / cost+margin — see “Safety floor”)
                </span>
              )}
            </span>
            <span className={`text-[10px] ${out.is_profit ? "text-emerald-400" : "text-red-300"}`}>
              your profit on this call ≈ {fmtINR(out.your_profit_inr)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 font-medium">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Sel({ label, list, value, onChange }: {
  label: string; list: CatalogModel[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <Field label={label}>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {list.length === 0 && <option value="">— none live —</option>}
        {list.map((m) => (
          <option key={m.catalog_id} value={m.catalog_id}>
            {m.display_name} — ₹{m.customer_price_per_min}/min
          </option>
        ))}
      </select>
    </Field>
  );
}

function Part({ label, value }: { label: string; value: number }) {
  return (
    <span className="text-gray-400">
      <b className="text-gray-200">{fmtINR(value || 0)}</b> <span className="text-gray-600">{label}</span>
    </span>
  );
}
