"use client";

// Call tab — the LiveKit call lifecycle. Visuals & helpers live in ./call/*
// (≤300-line rule):
//   call/ActiveSession.tsx  in-room voice UI (orb, visualizer, announcement track)
//   call/RoomStage.tsx      right column (LiveKit room or placeholders)
//   call/CallForm.tsx       left column (agent/mode/SIP inputs, start/end buttons)
//   call/hooks.ts           join watchdog, last-agent persistence, billing-summary poller
//   call/mic.ts             browser mic pre-flight
//   call/types.ts           CallState + shared constants
// THIS file owns the state machine only: idle → connecting → waiting_for_agent
// → connected → ending → ended/error.
import { useCallback, useMemo, useRef, useState } from "react";
import "@livekit/components-styles";
import { Agent, startCall } from "@/lib/api";
import { CallState } from "./call/types";
import {
  useJoinWatchdog, useLastAgent, useCallSummary, useEndBrowserCall,
} from "./call/hooks";
import { ensureMicReady } from "./call/mic";
import CallForm from "./call/CallForm";
import RoomStage from "./call/RoomStage";

export type { CallState } from "./call/types";

interface Props {
  agents: Agent[];
  onStarted: () => void;
  presetAgentId?: string;
  onPresetConsumed?: () => void;
  /**
   * P10: parent finished loading the agents catalog at least once. Start is
   * disabled until this is true so a click can never race initialization —
   * this is the "refresh the page and try again" failure mode at the UI
   * layer. Defaults to true so other embedders keep working.
   */
  agentsReady?: boolean;
}

export default function CallPanel({
  agents,
  onStarted,
  presetAgentId,
  onPresetConsumed,
  agentsReady = true,
}: Props) {
  const [mode, setMode] = useState<"browser" | "sip">("browser");
  const [agentId, setAgentId] = useState("");
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

  const { fetchCallSummary, activeSummaryPollRef } = useCallSummary({
    onMessage: setCallEndedMsg,
    onError: (m) => {
      setErr(m);
      setCallState("error");
      onStarted();
    },
    onRefresh: onStarted,
  });

  // Everyone who starts over a call invalidates any in-flight summary poll.
  const invalidateSummary = () => {
    activeSummaryPollRef.current += 1;
  };

  // Watch the "agent joining" window: fails fast with the REAL reason
  // (backend failure record) or a hard 30s worker-pickup timeout.
  const agentWaitSeconds = useJoinWatchdog({
    callState, callId, isDisconnectingRef,
    onFail: (message) => {
      setErr(message);
      setCallState("error");
      setSession(null);
    },
  });

  // Preselect an agent: preset > localStorage (last chosen) > first agent
  useLastAgent({ agents, presetAgentId, agentId, setAgentId, onPresetConsumed });

  const handleAgentSelect = (newId: string) => {
    setAgentId(newId);
    setCallEndedMsg("");
    setErr("");
    invalidateSummary();
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem("voice_agent_last_selected_id", newId);
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

  const endBrowserCall = useEndBrowserCall({
    isDisconnectingRef, callEndReasonRef, callId,
    sessionRoom: session?.room || "",
    setCallState, setSession, fetchCallSummary,
  });

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
    [callId, session, selected, fetchCallSummary]
  );

  const go = async () => {
    invalidateSummary();
    setErr("");
    setCallEndedMsg("");
    if (isDisconnectingRef.current) return;
    if (
      callState === "connecting" ||
      callState === "waiting_for_agent" ||
      callState === "connected" ||
      session !== null
    ) {
      return setErr("A call is already active. End the current call first.");
    }
    if (!agentsReady)
      return setErr("Loading your agents — one moment before starting a call.");
    if (!agentId) return setErr("Select an agent first.");
    const selectedAgent = agents.find((a) => a.id === agentId);
    if (!selectedAgent) return setErr("Selected agent not found.");
    if (mode === "sip" && !phone) return setErr("Enter a phone number for SIP calling.");

    console.log(`[CALL_START] agent_id=${agentId} mode=${mode}`);
    console.log(
      `[AGENT_SELECTED] agent_id=${agentId} name=${selectedAgent.name} mode=${selectedAgent.agent_mode || "assistant"}`
    );

    setBusy(true);
    setCallState("connecting");

    try {
      if (mode === "browser") {
        try {
          await ensureMicReady();
        } catch (micErr) {
          const errMsg = (micErr as Error).message;
          console.error(`[CALL_ERROR] ${errMsg}`);
          setErr(errMsg);
          setCallState("error");
          setBusy(false);
          return;
        }
      }

      const res = await startCall({
        agent_id: agentId,
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
      <CallForm
        agents={agents}
        agentsReady={agentsReady}
        agentId={agentId}
        onAgentSelect={handleAgentSelect}
        selected={selected}
        mode={mode}
        onMode={setMode}
        phone={phone}
        onPhone={setPhone}
        trunkId={trunkId}
        onTrunkId={setTrunkId}
        busy={busy}
        err={err}
        callEndedMsg={callEndedMsg}
        callState={callState}
        isCallActive={isCallActive}
        session={session}
        callId={callId}
        onGo={go}
        onEnd={endBrowserCall}
      />
      <RoomStage
        session={session}
        callState={callState}
        isDisconnectingRef={isDisconnectingRef}
        selected={selected}
        callId={callId}
        mode={mode}
        err={err}
        callEndedMsg={callEndedMsg}
        agentWaitSeconds={agentWaitSeconds}
        onRoomDisconnected={handleRoomDisconnected}
        onStateChange={setCallState}
        onAnnouncementFinished={handleAnnouncementFinished}
      />
    </div>
  );
}
