"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "@livekit/components-styles";
import { Agent, getCall } from "@/lib/index";
import CallSetupForm from "@/app/(workspace)/call/components/CallSetupForm";
import CallStage from "@/app/(workspace)/call/components/CallStage";
import useCallSession, {
  sipConcurrencyLimitFor,
} from "../hooks/useCallSession";
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
    activeSipCalls,
    updateActiveSipCall,
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

  const finishedSipCallsRef = useRef<Set<string>>(new Set());
  const activeSipIdsKey = activeSipCalls
    .filter((call) => call.status === "connected")
    .map((call) => call.id)
    .sort()
    .join("|");

  // SIP participants are not connected to this browser, so LiveKit disconnect
  // events cannot tell this page when a phone call ends. Poll every active
  // backend call record; GET /api/calls/{id} also reconciles a missing SIP
  // participant server-side, so a phone-side hangup clears within seconds.
  useEffect(() => {
    if (!activeSipIdsKey) return;
    const ids = activeSipIdsKey.split("|").filter(Boolean);
    let cancelled = false;
    let checking = false;

    const checkSipCalls = async () => {
      if (checking) return;
      checking = true;
      try {
        await Promise.all(
        ids.map(async (id) => {
          try {
            const call = await getCall(id);
            if (cancelled) return;
            updateActiveSipCall(id, {
              backendStatus: call.status,
              ...(call.phone ? { phone: call.phone } : {}),
            });
            if (
              (call.status !== "completed" && call.status !== "failed") ||
              finishedSipCallsRef.current.has(id)
            ) {
              return;
            }
            finishedSipCallsRef.current.add(id);
            const remaining = finishSipCall(id);
            await fetchCallSummaryRef.current(id);
            if (!cancelled && remaining > 0) {
              setCallState("connected");
            }
          } catch {
            // A temporary backend/network error should not end a live phone
            // call; the next poll or per-call End button can reconcile it.
          }
        }),
        );
      } finally {
        checking = false;
      }
    };

    void checkSipCalls();
    const timer = window.setInterval(() => void checkSipCalls(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSipIdsKey, finishSipCall, setCallState, updateActiveSipCall]);

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

  const sipConcurrencyLimit = Math.min(
    sipConcurrencyLimitFor(selected),
    activeSipCalls[0]?.concurrencyLimit ?? Number.POSITIVE_INFINITY,
  );
  const canDialAnother =
    mode === "sip" &&
    !session &&
    activeMode !== "browser" &&
    activeSipCalls.length < sipConcurrencyLimit;

  // function for starting the call
  async function go() {
    const willHaveAnotherSlot =
      activeSipCalls.length + 1 < sipConcurrencyLimit;
    const startedCallId = await GoStart({
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
    if (mode === "sip" && startedCallId && willHaveAnotherSlot) {
      setPhone("");
    }
  }

  const handleEndCall = (targetCallId?: string) =>
    endCurrentCall(fetchCallSummary, targetCallId);

  const isCallActive =
    activeSipCalls.length > 0 ||
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
        activeSipCalls={activeSipCalls}
        sipConcurrencyLimit={sipConcurrencyLimit}
        canDialAnother={canDialAnother}
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
        activeSipCalls={activeSipCalls}
        sipConcurrencyLimit={sipConcurrencyLimit}
        agentWaitSeconds={agentWaitSeconds}
        isDisconnecting={isDisconnectingRef.current}
        onStateChange={setCallState}
        onAnnouncementFinished={onAnnouncementFinished}
        onDisconnected={onRoomDisconnected}
      />
    </div>
  );
}
