"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
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

export type CallState =
  | "idle"
  | "connecting"
  | "waiting_for_agent"
  | "connected"
  | "ending"
  | "ended"
  | "error";

interface Props {
  agents: Agent[];
  onStarted: () => void;
  presetAgentId?: string;
  onPresetConsumed?: () => void;
}

const STATIC_AUDIO_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

const LAST_AGENT_KEY = "voice_agent_last_selected_id";

function ActiveSession({
  agent,
  callId,
  roomName,
  onStateChange,
  onAnnouncementFinished,
}: {
  agent?: Agent;
  callId: string;
  roomName: string;
  onStateChange: (state: CallState) => void;
  onAnnouncementFinished: () => void;
}) {
  const room = useRoomContext();
  const { state: vaState, audioTrack } = useVoiceAssistant();
  const participants = useParticipants();
  const [agentJoined, setAgentJoined] = useState(false);
  const [waitingLogged, setWaitingLogged] = useState(false);
  const announcementSpokeRef = useRef(false);
  const announcementFinishedRef = useRef(false);
  const [announcementDone, setAnnouncementDone] = useState(false);

  // Auto-start browser audio playout once room is connected
  useEffect(() => {
    if (room.state === "connected") {
      room.startAudio().catch(() => {});
    }
  }, [room, room.state]);

  // Track room connection and mic publication
  useEffect(() => {
    if (room.state === "connected") {
      console.log(`[LIVEKIT_CONNECTED] room=${roomName}`);
      console.log(`[MIC_PUBLISHED] room=${roomName}`);
    }
  }, [room.state, roomName]);

  // Monitor participants for the remote agent
  useEffect(() => {
    const remoteAgents = participants.filter((p) => !p.isLocal);
    if (remoteAgents.length > 0 && !agentJoined) {
      setAgentJoined(true);
      onStateChange("connected");
      const remote = remoteAgents[0];
      console.log(`[AGENT_JOINED] room=${roomName} identity=${remote.identity}`);
      console.log(
        `[AGENT_STARTED] room=${roomName} agent_id=${agent?.id || ""} mode=${agent?.agent_mode || "assistant"}`
      );
      if (agent?.agent_mode === "announcement") {
        console.log(`[ANNOUNCEMENT_STARTED] room=${roomName}`);
      } else {
        console.log(`[ASSISTANT_STARTED] room=${roomName}`);
      }
    } else if (remoteAgents.length === 0 && !agentJoined && !waitingLogged) {
      setWaitingLogged(true);
      console.log(`[AGENT_WAITING] room=${roomName} agent_id=${agent?.id || ""}`);
    }
  }, [participants, agentJoined, roomName, agent, waitingLogged, onStateChange]);

  // Track announcement playback state
  useEffect(() => {
    if (agent?.agent_mode === "announcement") {
      if (vaState === "speaking") {
        announcementSpokeRef.current = true;
      } else if (
        announcementSpokeRef.current &&
        !announcementFinishedRef.current &&
        (vaState === "idle" || vaState === "listening")
      ) {
        announcementFinishedRef.current = true;
        setAnnouncementDone(true);
        console.log(`[ANNOUNCEMENT_FINISHED] room=${roomName}`);
        onAnnouncementFinished();
      }
    }
  }, [vaState, agent, roomName, onAnnouncementFinished]);

  return (
    <div className="flex flex-col items-center gap-6 p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl max-w-md w-full animate-fade-in-up">
      <div
        className={`w-36 h-36 rounded-full flex items-center justify-center text-6xl transition-all duration-300 ${
          vaState === "speaking"
            ? "bg-green-500 animate-pulse shadow-lg shadow-green-500/50"
            : vaState === "listening"
              ? "bg-blue-500 shadow-lg shadow-blue-500/50"
              : vaState === "thinking"
                ? "bg-yellow-500 shadow-lg shadow-yellow-500/30 animate-pulse"
                : !agentJoined
                  ? "bg-amber-600 animate-pulse"
                  : announcementDone
                    ? "bg-indigo-600 shadow-lg shadow-indigo-500/30"
                    : "bg-gray-700"
        }`}
      >
        {vaState === "speaking"
          ? "🗣️"
          : vaState === "listening"
            ? "👂"
            : vaState === "thinking"
              ? "💭"
              : !agentJoined
                ? "⏳"
                : announcementDone
                  ? "📢"
                  : "🤖"}
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-1">
          {agent?.name || "Live Agent"}
        </h2>
        <p className="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-1">
          {agent?.agent_mode === "announcement"
            ? "📢 Announcement Mode"
            : "🎙️ Conversational Assistant"}
        </p>
        <p className="text-gray-300 text-sm font-medium">
          {!agentJoined
            ? "Waiting for agent to connect..."
            : vaState === "speaking"
              ? agent?.agent_mode === "announcement"
                ? "Playing announcement script..."
                : "Agent is speaking..."
              : announcementDone
                ? "Announcement completed. Call is active."
                : vaState === "listening"
                  ? "Listening to you..."
                  : vaState === "thinking"
                    ? "Thinking..."
                    : "Connected to agent"}
        </p>
        <p className="text-[11px] text-gray-500 mt-1">
          {participants.length} participant{participants.length !== 1 ? "s" : ""} in room
          {announcementDone && " • You can stay connected or press End Call"}
        </p>
      </div>

      {audioTrack && (
        <div className="w-full h-16">
          <BarVisualizer
            state={vaState}
            barCount={24}
            trackRef={audioTrack}
            className="h-full w-full"
          />
        </div>
      )}

      <StartAudio
        label="Click if audio is muted"
        className="mt-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-black px-4 py-1.5 text-xs font-semibold cursor-pointer"
      />

      <VoiceAssistantControlBar controls={{ leave: false, microphone: true }} />
    </div>
  );
}

export default function CallPanel({
  agents,
  onStarted,
  presetAgentId,
  onPresetConsumed,
}: Props) {
  const [mode, setMode] = useState<"browser" | "sip">("browser");
  const [agentId, setAgentId] = useState<string>(() => {
    if (presetAgentId && agents.some((a) => a.id === presetAgentId)) return presetAgentId;
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem(LAST_AGENT_KEY);
        if (saved && agents.some((a) => a.id === saved)) return saved;
      } catch {}
    }
    return agents[0]?.id || "";
  });
  const [phone, setPhone] = useState("");
  const [trunkId, setTrunkId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [callState, setCallState] = useState<CallState>("idle");
  const [session, setSession] = useState<{
    token: string;
    url: string;
    room: string;
  } | null>(null);
  const [callId, setCallId] = useState("");
  const [callEndedMsg, setCallEndedMsg] = useState("");

  const isDisconnectingRef = useRef(false);
  const callEndReasonRef = useRef<string | null>(null);
  const activeSummaryPollRef = useRef<number>(0);

  // Preselect an agent: preset > localStorage (last chosen) > first agent
  useEffect(() => {
    if (!agents.length) return;

    let targetId = "";
    if (presetAgentId && agents.some((a) => a.id === presetAgentId)) {
      targetId = presetAgentId;
      onPresetConsumed?.();
    } else if (agentId && agents.some((a) => a.id === agentId)) {
      targetId = agentId;
    } else {
      let savedAgentId: string | null = null;
      if (typeof window !== "undefined") {
        try {
          savedAgentId = localStorage.getItem(LAST_AGENT_KEY);
        } catch {}
      }
      if (savedAgentId && agents.some((a) => a.id === savedAgentId)) {
        targetId = savedAgentId;
      } else {
        targetId = agents[0].id;
      }
    }

    if (targetId) {
      if (targetId !== agentId) {
        setAgentId(targetId);
      }
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(LAST_AGENT_KEY, targetId);
        } catch {}
      }
      const found = agents.find((a) => a.id === targetId);
      if (found) {
        console.log(
          `[AGENT_SELECTED] agent_id=${found.id} name=${found.name} mode=${found.agent_mode || "assistant"}`
        );
      }
    }
  }, [agents, presetAgentId, agentId, onPresetConsumed]);

  const handleAgentSelect = (newId: string) => {
    setAgentId(newId);
    setCallEndedMsg("");
    setErr("");
    isDisconnectingRef.current = false;
    activeSummaryPollRef.current += 1;
    if (newId && typeof window !== "undefined") {
      try {
        localStorage.setItem(LAST_AGENT_KEY, newId);
      } catch {}
    }
    const found = agents.find((a) => a.id === newId);
    if (found) {
      console.log(
        `[AGENT_SELECTED] agent_id=${found.id} name=${found.name} mode=${found.agent_mode || "assistant"}`
      );
    }
  };

  const selected = useMemo(() => agents.find((a) => a.id === agentId), [agents, agentId]);

  const fetchCallSummary = async (cid: string) => {
    if (!cid) {
      setCallEndedMsg("Call ended. Ready to start a new call.");
      return;
    }
    const pollId = ++activeSummaryPollRef.current;
    setCallEndedMsg("Finalizing call & calculating billing summary…");

    // Poll until billing is finalized and written to DB (up to 12s)
    let attempts = 0;
    const maxAttempts = 12;
    while (attempts < maxAttempts) {
      if (activeSummaryPollRef.current !== pollId) return;
      try {
        await new Promise((r) => setTimeout(r, attempts === 0 ? 800 : 1200));
        if (activeSummaryPollRef.current !== pollId) return;
        attempts++;
        const c = await getCall(cid);
        if (activeSummaryPollRef.current !== pollId) return;
        const costInr = (c.cost as any)?.client_price_inr;
        const duration = c.duration_seconds ?? 0;
        const isFinalized = c.status === "completed" || c.status === "failed";

        // Check if billing is ready: either cost is posted or duration is > 0
        if (costInr !== undefined && costInr !== null && (Number(costInr) > 0 || duration > 0)) {
          const finalCost = Number(costInr) || 0;
          setCallEndedMsg(
            `Call completed • ${duration}s • Billed ₹${finalCost.toFixed(2)} • Wallet balance updated`
          );
          onStarted(); // triggers refreshWallet() and refreshAgents() in parent
          return;
        }

        if (isFinalized && duration > 0) {
          const finalCost = Number(costInr || 0);
          setCallEndedMsg(
            `Call completed • ${duration}s • Billed ₹${finalCost.toFixed(2)} • Wallet balance updated`
          );
          onStarted();
          return;
        }
      } catch {
        // continue polling on error
      }
    }

    if (activeSummaryPollRef.current !== pollId) return;
    // Final attempt fallback
    try {
      const c = await getCall(cid);
      if (activeSummaryPollRef.current !== pollId) return;
      const costInr = Number((c.cost as any)?.client_price_inr || 0);
      const duration = c.duration_seconds ?? 0;
      setCallEndedMsg(
        `Call completed • ${duration}s • Billed ₹${costInr.toFixed(2)} • Wallet balance updated`
      );
      onStarted();
    } catch {
      if (activeSummaryPollRef.current === pollId) {
        setCallEndedMsg("Call ended. Ready to start a new call.");
      }
    }
  };

  const endBrowserCall = async () => {
    if (isDisconnectingRef.current) return;
    isDisconnectingRef.current = true;
    callEndReasonRef.current = "user_ended";
    console.log(`[CALL_END_REQUESTED] source=frontend call_id=${callId}`);
    setCallState("ending");

    const curCallId = callId;
    const curRoom = session?.room || "";

    try {
      if (curCallId) {
        await endCall(curCallId).catch((e) =>
          console.warn("endCall backend call error:", e)
        );
      }
    } catch {
      // ignore backend error on end
    } finally {
      console.log(`[CALL_ENDED] room=${curRoom} call_id=${curCallId} reason=user_ended`);
      setTimeout(() => {
        setSession(null);
        setCallState("ended");
        isDisconnectingRef.current = false;
        callEndReasonRef.current = null;
        fetchCallSummary(curCallId);
      }, 300);
    }
  };

  const handleAnnouncementFinished = useCallback(() => {
    if (!selected) return;
    if (selected.agent_mode === "announcement" && selected.end_after_announcement) {
      console.log(`[CALL_END_REQUESTED] source=announcement call_id=${callId}`);
      callEndReasonRef.current = "announcement_completed";
    }
  }, [selected, callId]);

  const handleRoomDisconnected = useCallback(
    (reason?: any) => {
      if (isDisconnectingRef.current) return;
      isDisconnectingRef.current = true;
      const curCallId = callId;
      const curRoom = session?.room || "";

      let finalReason = callEndReasonRef.current;
      if (!finalReason) {
        if (selected?.agent_mode === "announcement" && selected?.end_after_announcement) {
          finalReason = "announcement_completed";
        } else if (reason === 5 || String(reason).includes("5") || String(reason).includes("ROOM_DELETED")) {
          finalReason = "completed";
        } else if (reason === 7 || String(reason).includes("7") || String(reason).includes("JOIN_FAILURE")) {
          finalReason = "connection_error";
        } else {
          finalReason = "room_disconnected";
        }
      }

      console.log(`[CALL_ENDED] room=${curRoom} call_id=${curCallId} reason=${finalReason}`);

      setCallState("ending");
      setTimeout(() => {
        setSession(null);
        setCallState("ended");
        isDisconnectingRef.current = false;
        callEndReasonRef.current = null;
        fetchCallSummary(curCallId);
      }, 250);
    },
    [callId, session, selected]
  );

  const go = async () => {
    activeSummaryPollRef.current += 1;
    setErr("");
    setCallEndedMsg("");
    isDisconnectingRef.current = false;
    if (
      callState === "connecting" ||
      callState === "waiting_for_agent" ||
      callState === "connected" ||
      session !== null
    ) {
      return setErr("A call is already active. End the current call first.");
    }
    let targetAgentId = agentId;
    if (!targetAgentId && agents.length > 0) {
      targetAgentId = presetAgentId || agents[0].id;
      setAgentId(targetAgentId);
    }
    if (!targetAgentId) return setErr("Select an agent first.");
    const selectedAgent = agents.find((a) => a.id === targetAgentId);
    if (!selectedAgent) return setErr("Selected agent not found.");
    if (mode === "sip" && !phone) return setErr("Enter a phone number for SIP calling.");

    console.log(`[CALL_START] agent_id=${targetAgentId} mode=${mode}`);
    console.log(
      `[AGENT_SELECTED] agent_id=${targetAgentId} name=${selectedAgent.name} mode=${selectedAgent.agent_mode || "assistant"}`
    );

    setBusy(true);
    setCallState("connecting");

    try {
      if (mode === "browser") {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
          stream.getTracks().forEach((t) => t.stop());
          const AC =
            window.AudioContext ||
            (window as unknown as { webkitAudioContext?: typeof AudioContext })
              .webkitAudioContext;
          if (AC) await new AC().resume();
        } catch {
          const errMsg =
            "Microphone access denied. Please allow microphone access in your browser settings.";
          console.error(`[CALL_ERROR] ${errMsg}`);
          setErr(errMsg);
          setCallState("error");
          setBusy(false);
          return;
        }
      }

      const res = await startCall({
        agent_id: targetAgentId,
        mode,
        phone: mode === "sip" ? phone : undefined,
        sip_trunk_id: trunkId || undefined,
      });

      console.log(`[ROOM_CREATED] room=${res.room} call_id=${res.call_id}`);
      setCallId(res.call_id);

      if (mode === "sip") {
        onStarted();
        setCallState("connected");
        setCallEndedMsg("SIP call dispatched — agent is dialing");
        setBusy(false);
        return;
      }

      if (!res.token || !res.url) {
        const errMsg =
          "LiveKit server returned empty token or URL. Please verify backend status.";
        console.error(`[CALL_ERROR] ${errMsg}`);
        setErr(errMsg);
        setCallState("error");
        setBusy(false);
        return;
      }

      console.log(`[TOKEN_CREATED] room=${res.room}`);
      console.log(`[LIVEKIT_CONNECT_START] room=${res.room} url=${res.url}`);

      setSession({ token: res.token, url: res.url, room: res.room });
      setCallState("waiting_for_agent");
      onStarted();
    } catch (e) {
      const errMsg = (e as Error).message || "Call setup failed";
      console.error(`[CALL_ERROR] ${errMsg}`);
      setErr(`Agent failed to start: ${errMsg}`);
      setCallState("error");
    } finally {
      setBusy(false);
    }
  };

  const isCallActive =
    (callState === "connecting" ||
      callState === "waiting_for_agent" ||
      callState === "connected" ||
      callState === "ending") &&
    session !== null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
        <h2 className="text-xl font-bold mb-4">⚡ Start a Call</h2>

        <label className="text-xs text-gray-400 font-medium">Agent</label>
        <select
          value={agentId}
          disabled={isCallActive}
          onChange={(e) => handleAgentSelect(e.target.value)}
          onClick={() => {
            if (agentId) {
              setCallEndedMsg("");
              setErr("");
              isDisconnectingRef.current = false;
            }
          }}
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
              ? selected.end_after_announcement
                ? "Announcement mode: plays fixed script, then automatically ends the call."
                : "Announcement mode: plays fixed script and keeps call open until you end it."
              : "Assistant mode: greets you on connect, then listens and converses across turns."}
          </p>
        ) : (
          <p className="text-[11px] text-gray-500 mb-4">
            Create an agent, then select it here. The call uses only the agent you pick.
          </p>
        )}

        <label className="text-xs text-gray-400 font-medium">Call mode</label>
        <div className="grid grid-cols-2 gap-1 mt-1 mb-4 bg-gray-800/80 border border-gray-700/50 p-1 rounded-xl">
          <button
            type="button"
            disabled={isCallActive}
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
            disabled={isCallActive}
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
              <label className="text-xs text-gray-400 font-medium">
                Phone number (E.164, e.g. +9180...)
              </label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91804xxxxxxx"
                className="input mt-1"
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
                className="input mt-1"
              />
            </div>
            <p className="text-[11px] text-gray-500">
              Requires a LiveKit SIP trunk + carrier credentials on the backend.
            </p>
          </div>
        )}

        {err && (
          <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3 mt-4">
            {err}
          </div>
        )}
        {callEndedMsg && !callEndedMsg.startsWith("Finalizing") && !err && (
          <div className="text-green-300 text-sm bg-green-500/10 border border-green-500/30 rounded-lg p-3 mt-4">
            {callEndedMsg}
          </div>
        )}

        <button
          onClick={go}
          disabled={busy || isCallActive || !agentId}
          className="w-full bg-green-600 hover:bg-green-500 text-white font-bold text-lg py-3 rounded-xl mt-4 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {busy || callState === "connecting"
            ? "Connecting..."
            : callState === "waiting_for_agent"
              ? "Waiting for agent..."
              : isCallActive
                ? "Call connected"
                : mode === "browser"
                  ? "📞 Start Voice Call"
                  : "📲 Dial Number"}
        </button>

        {isCallActive && (
          <button
            type="button"
            onClick={endBrowserCall}
            disabled={callState === "ending"}
            className="w-full mt-3 bg-red-600/90 hover:bg-red-500 text-white font-semibold py-2.5 rounded-xl transition-all shadow-md shadow-red-600/20 disabled:opacity-50"
          >
            {callState === "ending" ? "Ending call..." : "🔴 End Call"}
          </button>
        )}

        {mode === "browser" && session && (
          <p className="text-xs text-gray-500 mt-3">
            Room: <span className="font-mono text-blue-400">{session.room}</span> • Call:{" "}
            <span className="font-mono text-purple-400">{callId}</span>
          </p>
        )}
        {mode === "sip" && callId && !session && (
          <p className="text-xs text-green-400 mt-3">
            ✅ SIP call dispatched. The agent is dialing the number. View transcripts in Calls tab.
          </p>
        )}
      </div>

      {/* LiveKit room container */}
      <div className="flex items-center justify-center bg-gray-900 rounded-2xl border border-gray-800 min-h-[380px] p-4">
        {session ? (
          <LiveKitRoom
            token={session.token}
            serverUrl={session.url}
            connect={!isDisconnectingRef.current && (callState === "connecting" || callState === "waiting_for_agent" || callState === "connected")}
            audio={STATIC_AUDIO_OPTIONS}
            video={false}
            onDisconnected={handleRoomDisconnected}
            onError={(error) => {
              console.error(`[CALL_ERROR] LiveKitRoom error: ${error?.message || error}`);
              console.log(`[CALL_END_REQUESTED] source=error reason=${error?.message || error} call_id=${callId}`);
            }}
            className="w-full flex items-center justify-center"
          >
            <ActiveSession
              agent={selected}
              callId={callId}
              roomName={session.room}
              onStateChange={(st) => setCallState(st)}
              onAnnouncementFinished={handleAnnouncementFinished}
            />
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
            ) : callState === "error" ? (
              <>
                <div className="text-5xl mb-3">⚠️</div>
                <p className="text-sm text-red-400 font-semibold">Call Error</p>
                <p className="text-xs mt-1 text-gray-400">{err || "An error occurred"}</p>
              </>
            ) : mode === "browser" ? (
              <>
                <div className="text-6xl mb-3">🎙️</div>
                <p className="text-sm">
                  Select an agent, then press <b>Start Voice Call</b>.
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
