"use client";

import { useEffect, useRef, useState } from "react";
import {
  LiveKitRoom,
  VoiceAssistantControlBar,
  RoomAudioRenderer,
  useVoiceAssistant,
  BarVisualizer,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { Agent, startCall } from "@/lib/api";

function AgentView() {
  const { state, audioTrack } = useVoiceAssistant();
  return (
    <div className="flex flex-col items-center gap-6 p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl max-w-md w-full">
      <div
        className={`w-36 h-36 rounded-full flex items-center justify-center text-6xl transition-all duration-300 ${
          state === "speaking"
            ? "bg-green-500 animate-pulse shadow-lg shadow-green-500/50"
            : state === "listening"
              ? "bg-blue-500 shadow-lg shadow-blue-500/50"
              : "bg-gray-700"
        }`}
      >
        {state === "speaking" ? "🗣️" : state === "listening" ? "👂" : "🤖"}
      </div>
      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-1">Live Agent</h2>
        <p className="text-gray-400 text-sm font-medium">
          {state === "speaking"
            ? "Agent is speaking..."
            : state === "listening"
              ? "Listening to you..."
              : state === "thinking"
                ? "Thinking..."
                : "Connecting..."}
        </p>
      </div>
      {audioTrack && (
        <div className="w-full h-16">
          <BarVisualizer
            state={state}
            barCount={24}
            trackRef={audioTrack}
            className="h-full w-full"
          />
        </div>
      )}
      <VoiceAssistantControlBar controls={{ leave: true }} />
    </div>
  );
}

interface Props {
  agents: Agent[];
  onStarted: () => void;
  presetAgentId?: string;
  onPresetConsumed?: () => void;
}

export default function CallPanel({
  agents,
  onStarted,
  presetAgentId,
  onPresetConsumed,
}: Props) {
  const [mode, setMode] = useState<"browser" | "sip">("browser");
  const [agentId, setAgentId] = useState("");
  const [phone, setPhone] = useState("");
  const [trunkId, setTrunkId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [session, setSession] = useState<{
    token: string;
    url: string;
    room: string;
  } | null>(null);
  const [callId, setCallId] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Preselect an agent when the user pressed "Call" on a card. If no preset,
  // fall back to the first available agent.
  useEffect(() => {
    if (!agents.length) return;
    if (presetAgentId && agents.some((a) => a.id === presetAgentId)) {
      setAgentId(presetAgentId);
      onPresetConsumed?.();
    } else if (!agentId) {
      setAgentId(agents[0].id);
    }
  }, [agents, presetAgentId, agentId, onPresetConsumed]);

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );

  const go = async () => {
    setErr("");
    setSession(null);
    if (!agentId) return setErr("Select an agent first.");
    if (mode === "sip" && !phone)
      return setErr("Enter a phone number for SIP calling.");
    setBusy(true);
    try {
      const res = await startCall({
        agent_id: agentId,
        mode,
        phone: mode === "sip" ? phone : undefined,
        sip_trunk_id: trunkId || undefined,
      });
      setCallId(res.call_id);
      if (mode === "sip") {
        // SIP: no browser client; agent dials the number. Show status.
        setErr("");
        onStarted();
        return;
      }
      if (!res.token)
        return setErr("No token returned. Is the backend + LiveKit running?");
      setSession({ token: res.token, url: res.url, room: res.room });
      onStarted();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
        <h2 className="text-xl font-bold mb-4">⚡ Start a Call</h2>

        <label className="text-xs text-gray-400 font-medium">Agent</label>
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1 mb-4"
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        <label className="text-xs text-gray-400 font-medium">Call mode</label>
        <div className="flex gap-2 mt-1 mb-4">
          <button
            onClick={() => setMode("browser")}
            className={`flex-1 py-2 rounded-lg text-sm font-semibold ${mode === "browser" ? "bg-green-600" : "bg-gray-800"}`}
          >
            🌐 Browser (free)
          </button>
          <button
            onClick={() => setMode("sip")}
            className={`flex-1 py-2 rounded-lg text-sm font-semibold ${mode === "sip" ? "bg-blue-600" : "bg-gray-800"}`}
          >
            📞 SIP (real phone)
          </button>
        </div>

        {mode === "sip" && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 font-medium">
                Phone number (E.164, e.g. +9180...)
              </label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91804xxxxxxx"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">
                SIP trunk ID (optional)
              </label>
              <input
                value={trunkId}
                onChange={(e) => setTrunkId(e.target.value)}
                placeholder="sip trunk id registered in LiveKit"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm mt-1"
              />
            </div>
            <p className="text-[11px] text-gray-500">
              Requires a LiveKit SIP trunk (Telnyx/Twilio) + carrier credentials
              on the backend.
            </p>
          </div>
        )}

        {err && (
          <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3 mt-4">
            {err}
          </div>
        )}

        <button
          onClick={go}
          disabled={busy}
          className="w-full bg-green-600 hover:bg-green-500 text-white font-bold text-lg py-3 rounded-xl mt-4 disabled:opacity-50"
        >
          {busy
            ? "Connecting..."
            : mode === "browser"
              ? "📞 Start Voice Call"
              : "📲 Dial Number"}
        </button>

        {mode === "browser" && session && (
          <p className="text-xs text-gray-500 mt-3">
            Room:{" "}
            <span className="font-mono text-blue-400">{session.room}</span>
          </p>
        )}
        {mode === "sip" && callId && !session && (
          <p className="text-xs text-green-400 mt-3">
            ✅ SIP call dispatched. The agent is dialing the number. View
            transcripts below.
          </p>
        )}
      </div>

      {/* LiveKit room */}
      <div className="flex items-center justify-center bg-gray-900 rounded-2xl border border-gray-800 min-h-[320px]">
        {session ? (
          <LiveKitRoom
            token={session.token}
            serverUrl={session.url}
            connect={true}
            audio={{
              noiseSuppression: true,
              echoCancellation: true,
              autoGainControl: true,
            }}
            video={false}
            onDisconnected={() => setSession(null)}
            className="w-full flex items-center justify-center"
          >
            <AgentView />
            <RoomAudioRenderer />
          </LiveKitRoom>
        ) : (
          <div className="text-center text-gray-500 p-8">
            {mode === "browser" ? (
              <>
                <div className="text-6xl mb-3">🎙️</div>
                <p className="text-sm">
                  Configure an agent above, then press <b>Start Voice Call</b>.
                </p>
              </>
            ) : (
              <>
                <div className="text-6xl mb-3">📲</div>
                <p className="text-sm">
                  Enter a number, then press <b>Dial Number</b>.
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
