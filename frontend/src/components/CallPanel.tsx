"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  LiveKitRoom,
  VoiceAssistantControlBar,
  RoomAudioRenderer,
  StartAudio,
  useVoiceAssistant,
  BarVisualizer,
  useRoomContext,
  useParticipants,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { Agent, startCall, getCall, endCall } from "@/lib/api";

function AgentView({ onEnded }: { onEnded?: () => void }) {
  const { state, audioTrack } = useVoiceAssistant();
  const room = useRoomContext();
  const participants = useParticipants();
  const [hasHadRemote, setHasHadRemote] = useState(false);
  const [ended, setEnded] = useState(false);

  // Track if we ever had a remote agent — but don't cut off TTS goodbye
  useEffect(() => {
    const remoteCount = participants.filter((p) => !p.isLocal).length;
    if (remoteCount > 0) setHasHadRemote(true);
    // If we had remote and now none -> agent left -> call ended
    // IMPORTANT: if agent was speaking (goodbye TTS), wait 3s before marking ended
    // so the goodbye audio fully flushes to frontend
    if (hasHadRemote && remoteCount === 0 && !ended) {
      if (state === "speaking") {
        const t = setTimeout(() => {
          setEnded(true);
          onEnded?.();
        }, 3000);
        return () => clearTimeout(t);
      }
      setEnded(true);
      onEnded?.();
    }
  }, [participants, hasHadRemote, ended, onEnded, state]);

  // Also listen to room disconnected — delay to allow goodbye TTS to finish
  useEffect(() => {
    const handleDisconnected = () => {
      if (!ended) {
        // If disconnect happens during speaking (goodbye), give it time
        const delay = state === "speaking" ? 2500 : 500;
        setTimeout(() => {
          setEnded(true);
          onEnded?.();
        }, delay);
      }
    };
    room.on("disconnected", handleDisconnected);
    return () => {
      room.off("disconnected", handleDisconnected);
    };
  }, [room, ended, onEnded, state]);

  if (ended) {
    return (
      <div className="flex flex-col items-center gap-4 p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl max-w-md w-full animate-fade-in-up">
        <div className="w-20 h-20 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-3xl">
          ✅
        </div>
        <div className="text-center">
          <h2 className="text-xl font-bold text-white">Call Ended</h2>
          <p className="text-gray-400 text-sm mt-1">The agent has ended the call. Thank you!</p>
          <p className="text-gray-600 text-[11px] mt-2">Transcript &amp; billing are in the Calls tab.</p>
        </div>
      </div>
    );
  }

  return (
      <div className="flex flex-col items-center gap-6 p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl max-w-md w-full animate-fade-in-up">
      <div
        className={`w-36 h-36 rounded-full flex items-center justify-center text-6xl transition-all duration-300 ${
          state === "speaking"
            ? "bg-green-500 animate-pulse shadow-lg shadow-green-500/50"
            : state === "listening"
              ? "bg-blue-500 shadow-lg shadow-blue-500/50"
              : state === "thinking"
                ? "bg-yellow-500 shadow-lg shadow-yellow-500/30 animate-pulse"
                : "bg-gray-700"
        }`}
      >
        {state === "speaking" ? "🗣️" : state === "listening" ? "👂" : state === "thinking" ? "💭" : "🤖"}
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
                : "Connecting to agent..."}
        </p>
        <p className="text-[11px] text-gray-500 mt-1">
          {participants.length} participant{participants.length !== 1 ? "s" : ""} in room
        </p>
      </div>
      {audioTrack && (
        <div className="w-full h-16">
          <BarVisualizer state={state} barCount={24} trackRef={audioTrack} className="h-full w-full" />
        </div>
      )}
      <VoiceAssistantControlBar controls={{ leave: true, microphone: true }} />
    </div>
  );
}

function HearAgent() {
  const room = useRoomContext();
  useEffect(() => {
    // The Start button's click is over by the time the room connects, so the
    // browser may block agent audio until this runs (or the user taps the button).
    room.startAudio().catch(() => {});
  }, [room]);
  return (
    <StartAudio
      label="Click to hear the agent"
      className="mt-3 rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-black"
    />
  );
}

interface Props {
  agents: Agent[];
  onStarted: () => void;
  presetAgentId?: string;
  onPresetConsumed?: () => void;
}

export default function CallPanel({ agents, onStarted, presetAgentId, onPresetConsumed }: Props) {
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
  const [callEndedMsg, setCallEndedMsg] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Preselect an agent when the user pressed "Call" on a card
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

  // Poll call status when we have a callId and a browser session
  // IMPORTANT: after goodbye TTS, backend marks completed quickly, but frontend
  // must keep room alive 4s to hear full "Thank you for calling us..." before auto-cut
  useEffect(() => {
    if (!callId || !session) return;
    if (pollRef.current) clearInterval(pollRef.current);
    const check = async () => {
      try {
        const c = await getCall(callId);
        if (c.status === "completed" || c.status === "failed") {
          setCallEndedMsg(`Call ended (${c.status}) • ${c.duration_seconds}s • Billed ₹${(c.cost as any)?.client_price_inr ?? 0} • Remaining balance will update in Wallet`);
          // Give TTS goodbye time to fully play (2.5s in worker + network) then auto-cut
          setTimeout(() => {
            setSession(null);
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
          }, 4000);
        }
      } catch {
        // ignore, backend may not have record yet
      }
    };
    pollRef.current = setInterval(check, 2500);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [callId, session]);

  const handleRoomDisconnected = useCallback(() => {
    const curCallId = callId;
    setCallEndedMsg("Disconnected from room — call ended.");
    setTimeout(() => {
      setSession(null);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 1500);
    if (curCallId) {
      endCall(curCallId).catch(() => {});
    }
  }, [callId]);

  const handleAgentEnded = useCallback(() => {
    const curCallId = callId;
    setCallEndedMsg("Agent ended the call");
    setTimeout(() => {
      setSession(null);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 1500);
    if (curCallId) {
      endCall(curCallId).catch(() => {});
    }
  }, [callId]);

  const endBrowserCall = async () => {
    const curCallId = callId;
    setSession(null);
    setCallEndedMsg("Call ended. Select an agent, then start a new call.");
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (curCallId) {
      try {
        await endCall(curCallId);
      } catch (e) {
        console.warn("Could not end call on backend:", e);
      }
    }
  };

  const go = async () => {
    setErr("");
    setCallEndedMsg("");
    if (mode === "browser" && session) {
      return setErr("End the current call before starting another.");
    }
    if (!agentId) return setErr("Select an agent first.");
    if (mode === "sip" && !phone) return setErr("Enter a phone number for SIP calling.");
    setBusy(true);
    try {
      if (mode === "browser") {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          });
          stream.getTracks().forEach((t) => t.stop());
          const AC =
            window.AudioContext ||
            (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
          if (AC) await new AC().resume();
        } catch {
          setErr("Allow microphone access, then press Start Voice Call again.");
          return;
        }
      }
      const res = await startCall({
        agent_id: agentId,
        mode,
        phone: mode === "sip" ? phone : undefined,
        sip_trunk_id: trunkId || undefined,
      });
      setCallId(res.call_id);
      if (mode === "sip") {
        setErr("");
        onStarted();
        setCallEndedMsg("SIP call dispatched — agent is dialing");
        return;
      }
      if (!res.token) return setErr("No token returned. Is the backend + LiveKit running?");
      setSession({ token: res.token, url: res.url, room: res.room });
      onStarted();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const browserLive = mode === "browser" && session !== null;
  const selected = agents.find((a) => a.id === agentId);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
        <h2 className="text-xl font-bold mb-4">⚡ Start a Call</h2>

        <label className="text-xs text-gray-400 font-medium">Agent</label>
        <select
          value={agentId}
          disabled={browserLive}
          onChange={(e) => setAgentId(e.target.value)}
          className="input mt-1 mb-2"
        >
          <option value="">Select an agent…</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} — {a.agent_mode === "announcement" ? "Announcement" : "Assistant"}
            </option>
          ))}
        </select>
        {selected ? (
          <p className="text-[11px] text-gray-400 mb-4">
            {selected.agent_mode === "announcement"
              ? "Announcement mode: on connect the agent reads its script, then hangs up. It does not listen."
              : "Assistant mode: on connect the agent greets you, then listens and replies."}
          </p>
        ) : (
          <p className="text-[11px] text-gray-500 mb-4">Create an agent, then select it here. The call uses only the agent you pick.</p>
        )}

        <label className="text-xs text-gray-400 font-medium">Call mode</label>
        <div className="grid grid-cols-2 gap-1 mt-1 mb-4 bg-gray-800/80 border border-gray-700/50 p-1 rounded-xl">
          <button
            type="button"
            disabled={browserLive}
            onClick={() => setMode("browser")}
            className={`py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 ${
              mode === "browser"
                ? "bg-emerald-600 text-white shadow-md"
                : "text-gray-400 hover:text-white"
            }`}
          >
            🌐 Browser (free)
          </button>
          <button
            type="button"
            disabled={browserLive}
            onClick={() => setMode("sip")}
            className={`py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 ${
              mode === "sip"
                ? "bg-blue-600 text-white shadow-md"
                : "text-gray-400 hover:text-white"
            }`}
          >
            📞 SIP (real phone)
          </button>
        </div>

        {mode === "sip" && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 font-medium">Phone number (E.164, e.g. +9180...)</label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91804xxxxxxx"
                className="input mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 font-medium">SIP trunk ID (optional)</label>
              <input
                value={trunkId}
                onChange={(e) => setTrunkId(e.target.value)}
                placeholder="sip trunk id registered in LiveKit"
                className="input mt-1"
              />
            </div>
            <p className="text-[11px] text-gray-500">Requires a LiveKit SIP trunk + carrier credentials on the backend.</p>
          </div>
        )}

        {err && <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3 mt-4">{err}</div>}
        {callEndedMsg && !err && (
          <div className="text-green-300 text-sm bg-green-500/10 border border-green-500/30 rounded-lg p-3 mt-4">
            {callEndedMsg}
          </div>
        )}

        <button
          onClick={go}
          disabled={busy || browserLive || !agentId}
          className="w-full bg-green-600 hover:bg-green-500 text-white font-bold text-lg py-3 rounded-xl mt-4 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy
            ? "Connecting..."
            : browserLive
              ? "Call connected"
              : mode === "browser"
                ? "📞 Start Voice Call"
                : "📲 Dial Number"}
        </button>
        {browserLive && (
          <>
            <button
              type="button"
              onClick={endBrowserCall}
              className="w-full mt-2 border border-gray-600 text-gray-200 font-semibold py-2.5 rounded-xl hover:bg-gray-800"
            >
              End call
            </button>
            <p className="text-xs text-amber-200/90 mt-2">
              Connected. Start Voice Call stays disabled until you end this call. Then pick another agent and start again.
            </p>
          </>
        )}

        {mode === "browser" && session && (
          <p className="text-xs text-gray-500 mt-3">
            Room: <span className="font-mono text-blue-400">{session.room}</span> • Call: <span className="font-mono text-purple-400">{callId}</span>
          </p>
        )}
        {mode === "sip" && callId && !session && (
          <p className="text-xs text-green-400 mt-3">✅ SIP call dispatched. The agent is dialing the number. View transcripts in Calls tab.</p>
        )}
      </div>

      {/* LiveKit room */}
      <div className="flex items-center justify-center bg-gray-900 rounded-2xl border border-gray-800 min-h-[380px] p-4">
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
            onDisconnected={handleRoomDisconnected}
            className="w-full flex items-center justify-center"
          >
            <AgentView onEnded={handleAgentEnded} />
            <HearAgent />
            <RoomAudioRenderer />
          </LiveKitRoom>
        ) : (
          <div className="text-center text-gray-500 p-8">
            {callEndedMsg ? (
              <>
                <div className="text-5xl mb-3">✅</div>
                <p className="text-sm text-white font-semibold">Last call ended</p>
                <p className="text-xs mt-1 text-gray-400">{callEndedMsg}</p>
                <p className="text-xs mt-3">Start a new call from the left panel.</p>
              </>
            ) : mode === "browser" ? (
              <>
                <div className="text-6xl mb-3">🎙️</div>
                <p className="text-sm">
                  Select an agent, then press <b>Start Voice Call</b>. The agent speaks when the call connects.
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
