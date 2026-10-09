"use client";
// Left column of AgentConfigForm: identity, mode, voice settings, knowledge.
import CostEstimate from "./CostEstimate";
import { Toggle } from "./ProviderOptions";
import { GENDER_VOICE_HINT, LANGUAGES } from "./constants";
import type { LeftState, LeftSetters } from "./columnTypes";

export type { LeftState, LeftSetters } from "./columnTypes";

export default function LeftColumn({ v, set }: { v: LeftState; set: LeftSetters }) {
  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs text-gray-400 font-medium">Agent name</label>
        <input
          value={v.name}
          onChange={(e) => set.setName(e.target.value)}
          placeholder="e.g. Kavya"
          className="input mt-1"
        />
      </div>
      {v.mode !== "announcement" && (
        <div>
          <label className="text-xs text-gray-400 font-medium">Greeting</label>
          <textarea
            value={v.greeting}
            onChange={(e) => set.setGreeting(e.target.value)}
            rows={2}
            placeholder="Namaste! Main Kavya hoon..."
            className="input mt-1"
          />
        </div>
      )}

      <div>
        <label className="text-xs text-gray-400 font-medium">Fallback response</label>
        <textarea
          value={v.fallbackResponse}
          onChange={(e) => set.setFallbackResponse(e.target.value)}
          rows={2}
          placeholder="Please hold on, I am having a temporary issue."
          className="input mt-1"
        />
        <p className="text-[11px] text-gray-500 mt-1">Spoken when there is a temporary network, provider, or server problem.</p>
      </div>

      {v.mode !== "announcement" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response timeout (seconds)</label>
            <input
              type="number"
              min={15}
              value={v.noResponseTimeout}
              onChange={(e) => set.setNoResponseTimeout(Number(e.target.value))}
              className="input mt-1"
            />
            <p className="text-[11px] text-gray-500 mt-1">Recommended: 30 seconds.</p>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response closing message</label>
            <textarea
              value={v.noResponseMessage}
              onChange={(e) => set.setNoResponseMessage(e.target.value)}
              rows={2}
              className="input mt-1"
            />
          </div>
        </div>
      )}

      <div>
        <label className="text-xs text-gray-400 font-medium">Agent mode</label>
        <div className="grid grid-cols-2 gap-2 mt-1">
          <button
            type="button"
            onClick={() => set.setMode("assistant")}
            className={`py-2 rounded-lg text-sm font-semibold border ${v.mode === "assistant" ? "bg-green-600 border-green-500" : "bg-gray-800 border-gray-700"}`}
          >
            💬 Assistant
          </button>
          <button
            type="button"
            onClick={() => set.setMode("announcement")}
            className={`py-2 rounded-lg text-sm font-semibold border ${v.mode === "announcement" ? "bg-blue-600 border-blue-500" : "bg-gray-800 border-gray-700"}`}
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

      {v.mode === "announcement" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">Fixed script (announcement)</label>
            <textarea
              value={v.announceText}
              onChange={(e) => set.setAnnounceText(e.target.value)}
              rows={3}
              placeholder="Namaste! Ye ek reminder hai..."
              className="w-full bg-gray-800 border border-blue-600/40 rounded-lg px-3 py-2 text-sm mt-1"
            />
          </div>
          <Toggle
            on={v.endAfterAnnouncement}
            set={set.setEndAfterAnnouncement}
            label="End call after announcement"
            hint="Automatically hang up when script finishes (default: keep call open)"
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-400 font-medium">Personality</label>
          <select
            value={v.personality}
            onChange={(e) => set.setPersonality(e.target.value)}
            className="input mt-1"
          >
            {["friendly", "professional", "cautious", "playful", "formal"].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        {v.mode !== "announcement" && (
          <>
            <div>
              <label className="text-xs text-gray-400 font-medium">Language</label>
              <select
                value={v.language}
                onChange={(e) => set.setLanguage(e.target.value)}
                className="input mt-1"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-gray-500">
                Drives STT language and the TTS locale the agent speaks in.
              </p>
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">Voice gender</label>
              <select
                value={v.gender}
                onChange={(e) => set.setGender(e.target.value)}
                className="input mt-1"
              >
                <option value="female">Female</option>
                <option value="male">Male</option>
                <option value="neutral">Neutral</option>
              </select>
              <p className="mt-1 text-[10px] text-gray-500">
                {GENDER_VOICE_HINT[v.gender] || GENDER_VOICE_HINT.female}
              </p>
            </div>
          </>
        )}
      </div>

      {v.mode === "assistant" && (
        <div className="space-y-2">
          <Toggle on={v.memoryEnabled} set={set.setMemoryEnabled} label="🧠 Conversation memory" hint="Agent remembers this customer across calls" />
          <Toggle on={v.recordingEnabled} set={set.setRecordingEnabled} label="🎙️ Call recording" hint="Record the audio via LiveKit Egress" />
        </div>
      )}

      <div>
        <label className="text-xs text-gray-400 font-medium">Max concurrent calls</label>
        <input
          type="number"
          min={1}
          value={v.maxConcurrency}
          onChange={(e) => set.setMaxConcurrency(Number(e.target.value))}
          className="input mt-1"
        />
        <div className="mt-1.5">
          <CostEstimate
            mode={v.mode}
            llmId={v.picked.llm}
            sttId={v.picked.stt}
            ttsId={v.picked.tts}
            teleId={v.picked.telephony}
            maxConcurrency={v.maxConcurrency}
          />
        </div>
      </div>

      {v.mode === "assistant" && (
        <>
          <div>
            <label className="text-xs text-gray-400 font-medium">Knowledge base (pasted text / notes)</label>
            <textarea
              value={v.knowledgeText}
              disabled={!!v.file || v.savedDocuments.length > 0}
              onChange={(e) => set.setKnowledgeText(e.target.value)}
              rows={5}
              placeholder="Company facts, FAQs, product info..."
              className="input mt-1"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">System prompt (optional)</label>
            <textarea
              value={v.systemPrompt}
              onChange={(e) => set.setSystemPrompt(e.target.value)}
              rows={3}
              placeholder="Extra instructions for the agent..."
              className="input mt-1"
            />
          </div>

          <div className="bg-gray-800/40 rounded-xl border border-gray-800 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 font-medium uppercase">FAQ (Q&A pairs)</span>
              <button onClick={() => set.setFaq((f) => [...f, { q: "", a: "" }])} className="text-xs text-blue-400">
                + Add
              </button>
            </div>
            {v.faq.length === 0 && <p className="text-[11px] text-gray-500">No FAQs yet. Add Q&A the agent should know.</p>}
            <div className="space-y-2">
              {v.faq.map((item, i) => (
                <div key={i} className="grid grid-cols-1 gap-1">
                  <input
                    value={item.q}
                    onChange={(e) => set.setFaq((f) => f.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)))}
                    placeholder="Question"
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                  />
                  <div className="flex gap-1">
                    <input
                      value={item.a}
                      onChange={(e) => set.setFaq((f) => f.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)))}
                      placeholder="Answer"
                      className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                    />
                    <button onClick={() => set.setFaq((f) => f.filter((_, j) => j !== i))} className="text-red-400 text-xs px-2">
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-400 font-medium">Upload knowledge file (.txt/.md/.csv/.json/.pdf)</label>
            {v.savedDocuments.length > 0 && (
              <div className="mb-2 rounded-lg border border-blue-500/30 bg-blue-500/10 p-2 text-xs">
                <div className="font-medium">Saved knowledge file</div>
                {v.savedDocuments.map((d, i) => (
                  <div key={`${d.name}-${i}`} className="flex justify-between text-gray-300">
                    <span>{d.name}</span>
                    <button type="button" onClick={() => set.setSavedDocuments((docs) => docs.filter((_, j) => j !== i))} className="text-red-400">
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
            <input
              type="file"
              disabled={v.hasText}
              onChange={(e) => set.setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-gray-400 mt-1 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-white"
            />
          </div>
        </>
      )}
    </div>
  );
}
