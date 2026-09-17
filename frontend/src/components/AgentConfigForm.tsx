"use client";

import { useMemo, useState } from "react";
import {
  Catalog,
  ProviderDef,
  addKnowledge,
  setKnowledge,
  createAgent,
  updateAgent,
  Agent,
} from "@/lib/api";

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
  const [personality, setPersonality] = useState(editing?.voice_personality || "friendly");
  const [language, setLanguage] = useState(editing?.language || "hi");
  const [memoryEnabled, setMemoryEnabled] = useState(editing?.memory_enabled ?? true);
  const [recordingEnabled, setRecordingEnabled] = useState(editing?.recording_enabled ?? true);
  const [maxConcurrency, setMaxConcurrency] = useState(editing?.max_concurrency ?? 1);
  const [knowledgeText, setKnowledgeText] = useState(editing?.knowledge?.text || "");
  const [systemPrompt, setSystemPrompt] = useState(editing?.knowledge?.system_prompt || "");
  const [faq, setFaq] = useState<FaqItem[]>(editing?.knowledge?.faq || []);
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
    return !!(p.llm_fallback || p.stt_fallback || p.tts_fallback);
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
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
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
    for (const kind of kinds) {
      const pid = picked[kind];
      if (!pid) continue;
      cfg[kind] = buildProviderEntry(pid);
    }
    if (fallbackEnabled) {
      for (const kind of fallbackKinds) {
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
    setBusy(true);
    try {
      const body = {
        name,
        description: editing?.description || "Self-service agent",
        greeting,
        language,
        voice_personality: personality,
        agent_mode: mode,
        announce_text: mode === "announcement" ? announceText : "",
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

  const visibleKinds = mode === "announcement" ? kinds.filter((k) => k === "tts" || k === "telephony") : kinds;

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
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 font-medium">Greeting</label>
          <textarea
            value={greeting}
            onChange={(e) => setGreeting(e.target.value)}
            rows={2}
            placeholder="Namaste! Main Kavya hoon..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
            />
            <p className="text-[11px] text-gray-500 mt-1">Recommended: 30 seconds.</p>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response closing message</label>
            <textarea
              value={noResponseMessage}
              onChange={(e) => setNoResponseMessage(e.target.value)}
              rows={2}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">Personality</label>
            <select
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
            >
              {["hi", "en", "hi-Latn", "multi"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
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
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">System prompt (optional)</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={3}
                placeholder="Extra instructions for the agent..."
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
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
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
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

        {/* Fallback providers */}
        <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 border-dashed">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-semibold">🔁 Fallback Providers</span>
            <button
              type="button"
              onClick={() => setFallbackEnabled(!fallbackEnabled)}
              className={`text-xs px-3 py-1 rounded-full border ${fallbackEnabled ? "bg-green-600 border-green-500 text-white" : "bg-gray-800 border-gray-700 text-gray-400"}`}
            >
              {fallbackEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          <p className="text-[11px] text-gray-500 mb-3">
            If primary hits 429 rate-limit, the agent retries once with the fallback. Recommended: Groq primary + OpenRouter free fallback for LLM.
          </p>
          {fallbackEnabled && (
            <div className="space-y-3">
              {fallbackKinds.map((kind) => (
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
                        className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
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
            platform margin set in <code>.env</code>. Your daily margin and each call's total &amp; per-minute cost are shown in the{" "}
            <span className="text-blue-400">Wallet</span> / <span className="text-blue-400">Calls</span> tabs.
          </p>
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
