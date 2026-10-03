// Left column of the agent form: identity, mode, voice + conversation
// settings. Extracted from AgentConfigForm.tsx (verbatim JSX) — no behavior
// change; every value stays lifted in the parent form's state.
"use client";

import { GENDER_VOICE_HINT, LANGUAGES } from "./types";
import { Toggle } from "./Toggle";

export interface BasicFieldsProps {
  mode: string;
  name: string; setName: (v: string) => void;
  greeting: string; setGreeting: (v: string) => void;
  fallbackResponse: string; setFallbackResponse: (v: string) => void;
  noResponseTimeout: number; setNoResponseTimeout: (v: number) => void;
  noResponseMessage: string; setNoResponseMessage: (v: string) => void;
  setMode: (v: string) => void;
  announceText: string; setAnnounceText: (v: string) => void;
  endAfterAnnouncement: boolean; setEndAfterAnnouncement: (v: boolean) => void;
  personality: string; setPersonality: (v: string) => void;
  language: string; setLanguage: (v: string) => void;
  gender: string; setGender: (v: string) => void;
  vsCfg: { min: number; max: number; default: number };
  voiceSpeed: number; setVoiceSpeed: (v: number) => void;
  memoryEnabled: boolean; setMemoryEnabled: (v: boolean) => void;
  recordingEnabled: boolean; setRecordingEnabled: (v: boolean) => void;
  maxConcurrency: number; setMaxConcurrency: (v: number) => void;
}

export function BasicFields(p: BasicFieldsProps) {
  return (
    <>
      <div>
        <label className="text-xs text-gray-400 font-medium">Agent name</label>
        <input
          value={p.name}
          onChange={(e) => p.setName(e.target.value)}
          placeholder="e.g. Kavya"
          className="input mt-1"
        />
      </div>
      {p.mode !== "announcement" && (
        <div>
          <label className="text-xs text-gray-400 font-medium">Greeting</label>
          <textarea
            value={p.greeting}
            onChange={(e) => p.setGreeting(e.target.value)}
            rows={2}
            placeholder="Namaste! Main Kavya hoon..."
            className="input mt-1"
          />
        </div>
      )}

      <div>
        <label className="text-xs text-gray-400 font-medium">Fallback response</label>
        <textarea
          value={p.fallbackResponse}
          onChange={(e) => p.setFallbackResponse(e.target.value)}
          rows={2}
          placeholder="Please hold on, I am having a temporary issue."
          className="input mt-1"
        />
        <p className="text-[11px] text-gray-500 mt-1">Spoken when there is a temporary network, provider, or server problem.</p>
      </div>
      {p.mode !== "announcement" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response timeout (seconds)</label>
            <input
              type="number"
              min={15}
              value={p.noResponseTimeout}
              onChange={(e) => p.setNoResponseTimeout(Number(e.target.value))}
              className="input mt-1"
            />
            <p className="text-[11px] text-gray-500 mt-1">Recommended: 30 seconds.</p>
          </div>
          <div>
            <label className="text-xs text-gray-400 font-medium">No-response closing message</label>
            <textarea
              value={p.noResponseMessage}
              onChange={(e) => p.setNoResponseMessage(e.target.value)}
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
            onClick={() => p.setMode("assistant")}
            className={`py-2 rounded-lg text-sm font-semibold border ${p.mode === "assistant" ? "bg-green-600 border-green-500" : "bg-gray-800 border-gray-700"}`}
          >
            💬 Assistant
          </button>
          <button
            type="button"
            onClick={() => p.setMode("announcement")}
            className={`py-2 rounded-lg text-sm font-semibold border ${p.mode === "announcement" ? "bg-blue-600 border-blue-500" : "bg-gray-800 border-gray-700"}`}
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

      {p.mode === "announcement" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 font-medium">Fixed script (announcement)</label>
            <textarea
              value={p.announceText}
              onChange={(e) => p.setAnnounceText(e.target.value)}
              rows={3}
              placeholder="Namaste! Ye ek reminder hai..."
              className="w-full bg-gray-800 border border-blue-600/40 rounded-lg px-3 py-2 text-sm mt-1"
            />
          </div>
          <Toggle
            on={p.endAfterAnnouncement}
            set={p.setEndAfterAnnouncement}
            label="End call after announcement"
            hint="Automatically hang up when script finishes (default: keep call open)"
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-400 font-medium">Personality</label>
          <select
            value={p.personality}
            onChange={(e) => p.setPersonality(e.target.value)}
            className="input mt-1"
          >
            {["friendly", "professional", "cautious", "playful", "formal"].map((p2) => (
              <option key={p2} value={p2}>
                {p2}
              </option>
            ))}
          </select>
        </div>
        {p.mode !== "announcement" && (
          <>
            <div>
              <label className="text-xs text-gray-400 font-medium">Language</label>
              <select
                value={p.language}
                onChange={(e) => p.setLanguage(e.target.value)}
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
                value={p.gender}
                onChange={(e) => p.setGender(e.target.value)}
                className="input mt-1"
              >
                <option value="female">Female</option>
                <option value="male">Male</option>
                <option value="neutral">Neutral</option>
              </select>
              <p className="mt-1 text-[10px] text-gray-500">
                {GENDER_VOICE_HINT[p.gender] || GENDER_VOICE_HINT.female}
              </p>
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">
                Voice speed <span className="text-blue-300">{p.voiceSpeed.toFixed(2)}×</span>
              </label>
              <input
                type="range"
                min={p.vsCfg.min}
                max={p.vsCfg.max}
                step={0.05}
                value={p.voiceSpeed}
                onChange={(e) => p.setVoiceSpeed(Number(e.target.value))}
                className="w-full mt-2 accent-blue-500"
              />
              <p className="mt-1 text-[10px] text-gray-500">
                1.00 is the natural pace. Only applied when the chosen TTS provider supports speed
                control (range {p.vsCfg.min}× – {p.vsCfg.max}× set by the admin).
              </p>
            </div>
          </>
        )}
      </div>

      {p.mode === "assistant" && (
        <div className="space-y-2">
          <Toggle on={p.memoryEnabled} set={p.setMemoryEnabled} label="🧠 Conversation memory" hint="Agent remembers this customer across calls" />
          <Toggle on={p.recordingEnabled} set={p.setRecordingEnabled} label="🎙️ Call recording" hint="Record the audio via LiveKit Egress" />
        </div>
      )}
      <div>
        <label className="text-xs text-gray-400 font-medium">Max concurrent calls</label>
        <input
          type="number"
          min={1}
          value={p.maxConcurrency}
          onChange={(e) => p.setMaxConcurrency(Number(e.target.value))}
          className="input mt-1"
        />
      </div>
    </>
  );
}
