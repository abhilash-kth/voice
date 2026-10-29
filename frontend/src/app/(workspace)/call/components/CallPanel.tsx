"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "@livekit/components-styles";
import { Agent, getCall } from "@/lib/index";
import CallSetupForm from "@/app/(workspace)/call/components/CallSetupForm";
import CallStage from "@/app/(workspace)/call/components/CallStage";
import useCallSession from "../hooks/useCallSession";
import useCallSummary from "../hooks/useCallSummary";
import useAgentSelection from "../hooks/useAgentSelection";

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
  const [phone, setPhone] = useState("");
  const [trunkId, setTrunkId] = useState("");

  // hooks
  const {
    agentWaitSeconds,
    busy,
    callId,
    callState,
    err,
    isDisconnectingRef,
    session,
    setCallState,
    setErr,
    setSession,
    activeMode,
    finishSipCall,
    GoStart,
    endCurrentCall,
    handleAnnouncementFinished,
    handleRoomDisconnected,
  } = useCallSession();

  const { callEndedMsg, setCallEndedMsg, clearCallSummary, fetchCallSummary } =
    useCallSummary({ onStarted, setCallState, setErr });

  const fetchCallSummaryRef = useRef(fetchCallSummary);
  useEffect(() => {
    fetchCallSummaryRef.current = fetchCallSummary;
  }, [fetchCallSummary]);

  const finishedSipCallRef = useRef("");

  // SIP participants are not connected to this browser, so LiveKit disconnect
  // events cannot tell this page when the phone call ends. Poll the backend
  // call record and transition to the same summary flow used by browser calls.
  useEffect(() => {
    if (
      activeMode !== "sip" ||
      !callId ||
      session ||
      callState !== "connected"
    ) {
      return;
    }

    let cancelled = false;
    const checkSipCall = async () => {
      try {
        const call = await getCall(callId);
        if (
          cancelled ||
          (call.status !== "completed" && call.status !== "failed") ||
          finishedSipCallRef.current === callId
        ) {
          return;
        }
        finishedSipCallRef.current = callId;
        finishSipCall();
        await fetchCallSummaryRef.current(callId);
      } catch {
        // A temporary backend/network error should not end a live phone call;
        // the next poll (or the visible End call button) can still reconcile it.
      }
    };

    void checkSipCall();
    const timer = window.setInterval(() => void checkSipCall(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeMode, callId, callState, finishSipCall, session]);

  const { agentId, selected, handleAgentSelect } = useAgentSelection({
    agents,
    presetAgentId,
    onPresetConsumed,
    clearCallSummary,
    clearError: () => setErr(""),
  });

  // Supplies the current agent and summary callback to the call event handlers.
  const onAnnouncementFinished = useCallback(
    () => handleAnnouncementFinished(selected),
    [handleAnnouncementFinished, selected],
  );
  
  const onRoomDisconnected = useCallback(
    (reason?: unknown) =>
      handleRoomDisconnected(reason, selected, fetchCallSummary),
    [handleRoomDisconnected, selected, fetchCallSummary],
  );

  // function for starting the call
  async function go() {
    await GoStart({
      agentId: agentId,
      selectedAgent: selected,
      agentsReady: agentsReady,
      mode: mode,
      phone: phone,
      trunkId: trunkId,
      clearCallSummary,
      setCallEndedMsg,
      onStarted,
    });
  }

  const handleEndCall = () => endCurrentCall(fetchCallSummary);

  const isCallActive =
    activeMode !== null ||
    ((callState === "connecting" ||
      callState === "waiting_for_agent" ||
      callState === "connected" ||
      callState === "ending") &&
      session !== null);

  return (
    <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(320px,0.85fr)_minmax(0,1.35fr)] 2xl:gap-6">
      <CallSetupForm
        agents={agents}
        agentsReady={agentsReady}
        agentId={agentId}
        selected={selected}
        onAgentChange={handleAgentSelect}
        mode={mode}
        onModeChange={setMode}
        phone={phone}
        onPhoneChange={setPhone}
        trunkId={trunkId}
        onTrunkChange={setTrunkId}
        busy={busy}
        err={err}
        callState={callState}
        callEndedMsg={callEndedMsg}
        isCallActive={isCallActive}
        session={session}
        callId={callId}
        onStart={go}
        onEnd={handleEndCall}
      />
      <CallStage
        session={session}
        callState={callState}
        callEndedMsg={callEndedMsg}
        err={err}
        mode={activeMode ?? mode}
        selected={selected}
        callId={callId}
        agentWaitSeconds={agentWaitSeconds}
        isDisconnecting={isDisconnectingRef.current}
        onStateChange={setCallState}
        onAnnouncementFinished={onAnnouncementFinished}
        onDisconnected={onRoomDisconnected}
      />
    </div>
  );
}
