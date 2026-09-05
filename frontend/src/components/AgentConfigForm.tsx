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
  const [name, setName] = useState(editing?.name || "");
  const [greeting, setGreeting] = useState(editing?.greeting || "");
  const [mode, setMode] = useState(editing?.agent_mode || "assistant");
  const [announceText, setAnnounceText] = useState(
    editing?.announce_text || "",
  );
  const [personality, setPersonality] = useState(
    editing?.voice_personality || "friendly",
  );
  const [language, setLanguage] = useState(editing?.language || "hi");
  const [memoryEnabled, setMemoryEnabled] = useState(
    editing?.memory_enabled ?? true,
  );
  const [recordingEnabled, setRecordingEnabled] = useState(
    editing?.recording_enabled ?? true,
  );
  const [maxConcurrency, setMaxConcurrency] = useState(
    editing?.max_concurrency ?? 1,
  );
  const [knowledgeText, setKnowledgeText] = useState(
    editing?.knowledge?.text || "",
  );
  const [systemPrompt, setSystemPrompt] = useState(
    editing?.knowledge?.system_prompt || "",
  );
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
          llm: "groq_gpt_oss",
          stt: "deepgram_nova2",
          tts: "google_wavenet_hi",
          telephony: "browser",
        },
  );
  const [optionVals, setOptionVals] = useState<
    Record<string, Record<string, string>>
  >({});
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const providerByName = useMemo(() => {
    const m: Record<string, ProviderDef> = {};
    for (const k of kinds) for (const p of catalog.catalog[k]) m[p.id] = p;
    return m;
  }, [catalog, kinds]);

  const setPick = (kind: string, id: string) =>
    setPicked((p) => ({ ...p, [kind]: id }));

  const renderOptions = (kind: string) => {
    const pid = picked[kind];
    const p = providerByName[pid];
    if (!p?.options) return null;
    return Object.entries(p.options).map(([optName, optVals]) => {
      if (!optVals || optVals.length === 0) return null; // e.g. clone-only Fish Audio (no preset voices)
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
                {o}
              </option>
            ))}
          </select>
        </label>
      );
    });
  };

  const buildConfig = () =>
    Object.fromEntries(
      Object.entries(picked).map(([kind, pid]) => {
        const p = providerByName[pid];
        const opts = optionVals[pid] || {};
        // Carry the catalog default model/voice into the config so the backend
        // builder picks the right one even if the user never touched the dropdowns.
        if (p?.model && !opts.model) opts.model = p.model as string;
        if (kind === "tts" && p?.voice && !opts.voice)
          opts.voice = p.voice as string;
        return [kind, { id: pid, config: opts }];
      }),
    );

  const buildFaq = () => faq.filter((f) => f.q.trim() && f.a.trim());

  const submit = async () => {
    setErr("");
    if (!name) return setErr("Please give the agent a name.");
    // Announcement mode needs at least one script source: the fixed script OR the
    // greeting (which is used as the fallback). Only one is required.
    if (mode === "announcement" && !announceText.trim() && !greeting.trim()) {
      return setErr(
        "For Announcement mode, fill in a Fixed script (or a Greeting to use as its fallback).",
      );
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
        // Client-facing per-minute price is no longer set here — it is derived
        // on the backend from the actual provider costs (LLM + STT + TTS +
        // telephony) plus a margin configured in `.env`.
        memory_enabled: mode === "announcement" ? false : memoryEnabled,
        recording_enabled: mode === "announcement" ? false : recordingEnabled,
        max_concurrency: Math.max(1, Number(maxConcurrency) || 1),
        providers: buildConfig(),
        enabled: true,
      };
      const agent = editing
        ? await updateAgent(editing.id, body)
        : await createAgent(body);
      // Knowledge base (text/system prompt/FAQ/files) only applies to the
      // conversational assistant. Announcement mode just plays a fixed script.
      if (mode === "assistant") {
        await setKnowledge(agent.id, {
          text: knowledgeText,
          system_prompt: systemPrompt,
          faq: buildFaq(),
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

  // In "announcement" mode there is no STT and no LLM, so we hide those provider
  // panels — only TTS (the voice that reads the script) and telephony remain.
  const visibleKinds =
    mode === "announcement"
      ? kinds.filter((k) => k === "tts" || k === "telephony")
      : kinds;

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
      <span
        className={`w-10 h-6 rounded-full relative transition ${on ? "bg-blue-600" : "bg-gray-600"}`}
      >
        <span
          className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${on ? "left-[18px]" : "left-0.5"}`}
        />
      </span>
    </button>
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* left: name + personality + knowledge + FAQ */}
      <div className="space-y-4">
        <div>
          <label className="text-xs text-gray-400 font-medium">
            Agent name
          </label>
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
            <p className="text-[11px] text-gray-500 mt-1">
              Optional in Announcement mode — used only if the Fixed script
              below is left empty.
            </p>
          )}
        </div>

        {/* Agent mode: full assistant vs fixed-script announcement */}
        <div>
          <label className="text-xs text-gray-400 font-medium">
            Agent mode
          </label>
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
            <b>Announcement only:</b> plays a fixed script and hangs up — no
            STT, no LLM (a reminder/inform call).
          </p>
        </div>

        {mode === "announcement" && (
          <div>
            <label className="text-xs text-gray-400 font-medium">
              Fixed script (announcement)
            </label>
            <textarea
              value={announceText}
              onChange={(e) => setAnnounceText(e.target.value)}
              rows={3}
              placeholder="Namaste! Ye ek reminder hai. Aapka appointment kal subah 10 baje hai..."
              className="w-full bg-gray-800 border border-blue-600/40 rounded-lg px-3 py-2 text-sm mt-1"
            />
            <p className="text-[11px] text-gray-500 mt-1">
              Only one script source is required — this Fixed script, or the
              Greeting (used as fallback if empty). STT/LLM are not used or
              billed in this mode.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">
              Personality
            </label>
            <select
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
            >
              {[
                "friendly",
                "professional",
                "cautious",
                "playful",
                "formal",
              ].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">
              Language
            </label>
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

        {/* behaviour toggles — only for the conversational assistant */}
        {mode === "assistant" && (
          <div className="space-y-2">
            <Toggle
              on={memoryEnabled}
              set={setMemoryEnabled}
              label="🧠 Conversation memory"
              hint="Agent remembers this customer across calls"
            />
            <Toggle
              on={recordingEnabled}
              set={setRecordingEnabled}
              label="🎙️ Call recording"
              hint="Record the audio via LiveKit Egress"
            />
          </div>
        )}
        <div>
          <label className="text-xs text-gray-400 font-medium">
            Max concurrent calls
          </label>
          <input
            type="number"
            min={1}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(Number(e.target.value))}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
          />
          <p className="text-[11px] text-gray-500 mt-1">
            How many of these calls can run at the same time.
          </p>
        </div>

        {/* Knowledge base + system prompt + FAQ + file — only for the assistant.
            Announcement mode just plays a fixed script and hides all of these. */}
        {mode === "assistant" && (
          <>
            <div>
              <label className="text-xs text-gray-400 font-medium">
                Knowledge base (pasted text / notes)
              </label>
              <textarea
                value={knowledgeText}
                onChange={(e) => setKnowledgeText(e.target.value)}
                rows={5}
                placeholder="Company facts, FAQs, product info..."
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">
                System prompt (optional)
              </label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={3}
                placeholder="Extra instructions for the agent..."
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>

            {/* FAQ editor */}
            <div className="bg-gray-800/40 rounded-xl border border-gray-800 p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-400 font-medium uppercase">
                  FAQ (Q&A pairs)
                </span>
                <button
                  onClick={() => setFaq((f) => [...f, { q: "", a: "" }])}
                  className="text-xs text-blue-400"
                >
                  + Add
                </button>
              </div>
              {faq.length === 0 && (
                <p className="text-[11px] text-gray-500">
                  No FAQs yet. Add Q&amp;A the agent should know.
                </p>
              )}
              <div className="space-y-2">
                {faq.map((item, i) => (
                  <div key={i} className="grid grid-cols-1 gap-1">
                    <input
                      value={item.q}
                      onChange={(e) =>
                        setFaq((f) =>
                          f.map((x, j) =>
                            j === i ? { ...x, q: e.target.value } : x,
                          ),
                        )
                      }
                      placeholder="Question"
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                    />
                    <div className="flex gap-1">
                      <input
                        value={item.a}
                        onChange={(e) =>
                          setFaq((f) =>
                            f.map((x, j) =>
                              j === i ? { ...x, a: e.target.value } : x,
                            ),
                          )
                        }
                        placeholder="Answer"
                        className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                      />
                      <button
                        onClick={() =>
                          setFaq((f) => f.filter((_, j) => j !== i))
                        }
                        className="text-red-400 text-xs px-2"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400 font-medium">
                Upload knowledge file (.txt/.md/.csv/.json/.pdf)
              </label>
              <input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-400 mt-1 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-white"
              />
            </div>
          </>
        )}
      </div>

      {/* right: providers + pricing */}
      <div className="space-y-4">
        {visibleKinds.map((kind) => (
          <div
            key={kind}
            className="bg-gray-900 p-4 rounded-xl border border-gray-800"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold">{KIND_LABEL[kind]}</span>
              {kind === "telephony" && (
                <span className="text-[11px] text-gray-500">
                  browser = free, no carrier
                </span>
              )}
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
              {renderOptions(kind)}
            </div>
            {providerByName[picked[kind]]?.notes && (
              <p className="mt-2 text-[11px] text-amber-300/90 leading-snug">
                {providerByName[picked[kind]]!.notes}
              </p>
            )}
            {kind !== "telephony" && (
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-500">
                {Object.entries(providerByName[picked[kind]]?.cost || {}).map(
                  ([k, v]) => (
                    <span key={k} className="bg-gray-800 rounded px-2 py-0.5">
                      {k === "per_1k_in"
                        ? `in ₹${v}/1k`
                        : k === "per_1k_out"
                          ? `out ₹${v}/1k`
                          : k === "per_min"
                            ? `₹${v}/min`
                            : k === "per_1k_chars"
                              ? `₹${v}/1k chars`
                              : `${k}=${v}`}
                    </span>
                  ),
                )}
              </div>
            )}
          </div>
        ))}

        <div className="bg-gray-900 p-4 rounded-xl border border-gray-800">
          <label className="text-xs text-gray-400 font-medium">Pricing</label>
          <p className="text-[13px] text-gray-300 mt-1">
            The per-minute charge to the customer is{" "}
            <b>calculated automatically</b> from the provider costs (LLM + STT +
            TTS + telephony) plus a platform margin set in <code>.env</code>.
            Your daily margin and each call's total &amp; per-minute cost are
            shown in the
            <span className="text-blue-400"> Wallet</span> /{" "}
            <span className="text-blue-400">Calls</span> tabs.
          </p>
        </div>

        {err && (
          <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">
            {err}
          </div>
        )}

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
