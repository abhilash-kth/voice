import { useCallback, useEffect, useRef, useState } from "react";
import { CallState } from "../types/call-types";
import { Agent, endCall, getCall, startCall } from "@/lib";

// Values needed by the start-call action.
interface StartCallProps {
  agentId: string;
  selectedAgent?: Agent;
  mode: "browser" | "sip";
  phone: string;
  trunkId: string;
  agentsReady: boolean;
  clearCallSummary: () => void;
  setCallEndedMsg: (message: string) => void;
  onStarted: () => void;
}

export interface ActiveSipCall {
  id: string;
  phone: string;
  room: string;
  agentId: string;
  status: "connected" | "ending";
  backendStatus: string;
  startedAt: number;
  concurrencyLimit: number;
}

export function sipConcurrencyLimitFor(agent?: Agent): number {
  if (!agent) return 1;
  const agentLimit = Math.max(1, Number(agent.max_concurrency) || 1);
  const phoneChannels = agent.phone_number_channels;
  return phoneChannels == null
    ? agentLimit
    : Math.min(agentLimit, Math.max(1, Number(phoneChannels) || 1));
}

export default function useCallSession() {
  // Stores the current call state and LiveKit connection data.
  const [callState, setCallState] = useState<CallState>("idle");
  const [session, setSession] = useState<{
    token: string;
    url: string;
    room: string;
  } | null>(null);
  const [callId, setCallId] = useState("");
  // SIP calls have no browser LiveKit session, so track their mode explicitly.
  // Without this, a completed SIP call looked "connected" forever in local state.
  const [activeMode, setActiveMode] = useState<"browser" | "sip" | null>(null);
  const [activeSipCalls, setActiveSipCalls] = useState<ActiveSipCall[]>([]);

  // Tracks start progress, user-facing errors, and agent wait time.
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [agentWaitSeconds, setAgentWaitSeconds] = useState(0);

  // Refs prevent duplicate disconnect handling and remember the end reason.
  const isDisconnectingRef = useRef(false);
  const callEndReasonRef = useRef<string | null>(null);
  const activeSipCallsRef = useRef<ActiveSipCall[]>([]);

  const replaceActiveSipCalls = useCallback((next: ActiveSipCall[]) => {
    activeSipCallsRef.current = next;
    setActiveSipCalls(next);
  }, []);

  const updateActiveSipCall = useCallback(
    (id: string, patch: Partial<ActiveSipCall>) => {
      replaceActiveSipCalls(
        activeSipCallsRef.current.map((call) =>
          call.id === id ? { ...call, ...patch } : call,
        ),
      );
    },
    [replaceActiveSipCalls],
  );

  const removeActiveSipCall = useCallback(
    (finishedCallId: string): number => {
      const next = activeSipCallsRef.current.filter(
        (call) => call.id !== finishedCallId,
      );
      replaceActiveSipCalls(next);
      if (next.length > 0) {
        setActiveMode("sip");
        setCallState("connected");
        setCallId(next[next.length - 1].id);
      } else {
        setSession(null);
        setActiveMode(null);
        setCallState("ended");
        isDisconnectingRef.current = false;
        callEndReasonRef.current = null;
      }
      return next.length;
    },
    [replaceActiveSipCalls],
  );

  // Used when backend polling learns that a SIP call reached a terminal state.
  // With no id this keeps the old single-call behavior for compatibility.
  const finishSipCall = useCallback(
    (finishedCallId?: string): number => {
      if (finishedCallId) return removeActiveSipCall(finishedCallId);
      replaceActiveSipCalls([]);
      setSession(null);
      setActiveMode(null);
      setCallState("ended");
      isDisconnectingRef.current = false;
      callEndReasonRef.current = null;
      return 0;
    },
    [removeActiveSipCall, replaceActiveSipCalls],
  );

  // Polls for worker failure while the browser waits for the agent to join.
  useEffect(() => {
    if (callState !== "waiting_for_agent" || !callId) return;
    const startedAt = Date.now();
    let cancelled = false;

    const failWait = async (message: string) => {
      if (cancelled) return;
      console.error(`[CALL_ERROR] agent_join_failed: ${message}`);
      setErr(message);
      setCallState("error");
      isDisconnectingRef.current = true; // suppress handleRoomDisconnected takeover
      try {
        await endCall(callId); // release the room so "Try again" starts clean
      } catch {
        /* backend error on cleanup is fine — the state reset below still works */
      }
      setSession(null);
      setActiveMode(null);
      window.setTimeout(() => {
        isDisconnectingRef.current = false;
      }, 800);
    };

    setAgentWaitSeconds(0);
    const iv = window.setInterval(async () => {
      if (cancelled) return;
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setAgentWaitSeconds(elapsed);
      if (elapsed >= 30) {
        await failWait(
          "The agent did not join within 30 seconds. The agent worker may be stopped or busy — " +
            "check that exactly ONE agent worker is running (`python -m app.agents.worker`), close any " +
            "old worker windows, then try again.",
        );
        return;
      }
      try {
        const c = await getCall(callId);
        if (cancelled) return;
        if (c.status === "failed") {
          const why =
            (typeof c.usage === "object" &&
              c.usage !== null &&
              (c.usage as any).error) ||
            "the agent worker could not start this call";
          await failWait(`The agent could not start: ${why}`);
        }
      } catch {
        // backend briefly unreachable — keep waiting until the hard timeout
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, [callState, callId]);

  // Validates the setup and starts a browser or SIP call.
  // Returns the new call id, or null when validation/setup failed.
  async function GoStart(options: StartCallProps): Promise<string | null> {
    const {
      agentsReady,
      agentId,
      selectedAgent,
      mode,
      phone,
      trunkId,
      clearCallSummary,
      setCallEndedMsg,
      onStarted,
    } = options;

    clearCallSummary();
    setErr("");
    if (isDisconnectingRef.current || busy) return null;

    const failStart = (message: string): null => {
      setErr(message);
      return null;
    };

    if (!agentsReady)
      return failStart(
        "Loading your agents — one moment before starting a call.");
    if (!agentId) return failStart("Select an agent first.");
    if (!selectedAgent) return failStart("Selected agent not found.");

    const browserCallActive =
      session !== null ||
      activeMode === "browser" ||
      callState === "waiting_for_agent";
    const currentSipCalls = activeSipCallsRef.current;
    const sipLimit = sipConcurrencyLimitFor(selectedAgent);

    if (mode === "browser") {
      if (
        browserCallActive ||
        currentSipCalls.length > 0 ||
        activeMode !== null ||
        callState === "connecting" ||
        callState === "connected" ||
        callState === "ending"
      ) {
        return failStart(
          "A call is already active. End the current call first.");
      }
    } else {
      if (browserCallActive) {
        return failStart(
          "A browser call is already active. End it before dialing a SIP number.");
      }
      if (currentSipCalls.some((call) => call.agentId !== agentId)) {
        return failStart(
          "Finish the active SIP calls for the current agent before switching agents.");
      }
      if (currentSipCalls.length >= sipLimit) {
        return failStart(
          `Channel limit reached (${currentSipCalls.length}/${sipLimit}). ` +
            "End a SIP call or increase the agent limit / assigned number channels first.");
      }
    }

    if (
      mode === "sip" &&
      !["outbound", "both"].includes(selectedAgent.purpose || "outbound")
    ) {
      return failStart(
        "This agent is inbound-only. Choose an outbound or both-purpose agent to place a phone call.",
      );
    }
    if (mode === "sip" && !phone.trim())
      return failStart("Enter a phone number for SIP calling.");

    console.log(`[CALL_START] agent_id=${agentId} mode=${mode}`);
    console.log(
      `[AGENT_SELECTED] agent_id=${agentId} name=${selectedAgent.name} mode=${selectedAgent.agent_mode || "assistant"}`,
    );

    setBusy(true);
    setActiveMode(mode);
    // Keeping the aggregate state "connected" while dialing an additional
    // SIP destination prevents the existing calls from flickering/resetting.
    if (!(mode === "sip" && currentSipCalls.length > 0)) {
      setCallState("connecting");
    }

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
          setActiveMode(null);
          setBusy(false);
          return null;
        }
      }

      const res = await startCall({
        agent_id: agentId,
        mode,
        phone: mode === "sip" ? phone : undefined,
        // An assigned purchased number's trunk is backend-managed.
        sip_trunk_id: selectedAgent.phone_number_id
          ? undefined
          : trunkId || undefined,
      });

      console.log(`[ROOM_CREATED] room=${res.room} call_id=${res.call_id}`);
      setCallId(res.call_id);

      if (mode === "sip") {
        const effectiveLimit = Math.max(
          1,
          Number(res.concurrency?.limit) || sipLimit,
        );
        replaceActiveSipCalls([
          ...activeSipCallsRef.current.filter(
            (call) => call.id !== res.call_id,
          ),
          {
            id: res.call_id,
            phone: phone.trim(),
            room: res.room,
            agentId,
            status: "connected",
            backendStatus: "planned",
            startedAt: Date.now(),
            concurrencyLimit: effectiveLimit,
          },
        ]);
        onStarted();
        setSession(null);
        setCallState("connected");
        // Do not use callEndedMsg here: it represents a finished call. The SIP
        // status poll owns the transition to the ended/summary state.
        setCallEndedMsg("");
        setBusy(false);
        return res.call_id;
      }

      if (!res.token || !res.url) {
        const errMsg =
          "LiveKit server returned empty token or URL. Please verify backend status.";
        console.error(`[CALL_ERROR] ${errMsg}`);
        setErr(errMsg);
        setCallState("error");
        setActiveMode(null);
        setBusy(false);
        return null;
      }

      console.log(`[TOKEN_CREATED] room=${res.room}`);
      console.log(`[LIVEKIT_CONNECT_START] room=${res.room} url=${res.url}`);

      setSession({ token: res.token, url: res.url, room: res.room });
      setCallState("waiting_for_agent");
      onStarted();
      return res.call_id;
    } catch (e) {
      const errMsg = (e as Error).message || "Call setup failed";
      console.error(`[CALL_ERROR] ${errMsg}`);
      setErr(`Agent failed to start: ${errMsg}`);
      if (mode === "sip" && activeSipCallsRef.current.length > 0) {
        // A failed additional dial must not tear down calls already live.
        setActiveMode("sip");
        setCallState("connected");
      } else {
        setCallState("error");
        setActiveMode(null);
      }
      return null;
    } finally {
      setBusy(false);
    }
  }

  // Ends either the browser call or one specific SIP call, then starts the
  // summary polling for that call without disturbing other live SIP calls.
  async function endCurrentCall(
    fetchCallSummary: (callId: string) => Promise<void>,
    targetCallId?: string,
  ) {
    const sipTarget = targetCallId
      ? activeSipCallsRef.current.find((call) => call.id === targetCallId)
      : !session && activeMode === "sip"
        ? activeSipCallsRef.current.find((call) => call.id === callId) ||
          activeSipCallsRef.current[activeSipCallsRef.current.length - 1]
        : undefined;

    if (sipTarget) {
      if (sipTarget.status === "ending") return;
      updateActiveSipCall(sipTarget.id, { status: "ending" });
      if (activeSipCallsRef.current.length === 1) {
        setCallState("ending");
      }
      console.log(
        `[CALL_END_REQUESTED] source=user call_id=${sipTarget.id} room=${sipTarget.room}`,
      );
      try {
        await endCall(sipTarget.id).catch((e) =>
          console.warn("endCall backend call error:", e),
        );
      } finally {
        removeActiveSipCall(sipTarget.id);
        await fetchCallSummary(sipTarget.id);
        if (activeSipCallsRef.current.length > 0) {
          setActiveMode("sip");
          setCallState("connected");
        }
      }
      return;
    }

    if (isDisconnectingRef.current) return;
    isDisconnectingRef.current = true;
    callEndReasonRef.current = "user_ended";
    console.log(`[CALL_END_REQUESTED] source=user call_id=${callId}`);
    setCallState("ending");

    const curCallId = callId;
    const curRoom = session?.room || "";

    try {
      if (curCallId) {
        await endCall(curCallId).catch((e) =>
          console.warn("endCall backend call error:", e),
        );
      }
    } catch {
      // ignore backend error on end
    } finally {
      console.log(
        `[CALL_ENDED] room=${curRoom} call_id=${curCallId} reason=user_ended`,
      );
      setTimeout(() => {
        replaceActiveSipCalls([]);
        setSession(null);
        setActiveMode(null);
        setCallState("ended");
        isDisconnectingRef.current = false;
        callEndReasonRef.current = null;
        void fetchCallSummary(curCallId);
      }, 300);
    }
  }

  // Handles announcement completion before LiveKit disconnects the room.
  const handleAnnouncementFinished = useCallback(
    (selectedAgent?: Agent) => {
      if (!selectedAgent) return;
      if (
        selectedAgent.agent_mode === "announcement" &&
        selectedAgent.end_after_announcement
      ) {
        console.log(
          "[CALL_END_REQUESTED] source=announcement call_id=" + callId,
        );
        callEndReasonRef.current = "announcement_completed";
      }
    },
    [callId],
  );

  // Resets the session and requests the final summary after LiveKit disconnects.
  const handleRoomDisconnected = useCallback(
    (
      reason: unknown,
      selectedAgent: Agent | undefined,
      fetchCallSummary: (callId: string) => Promise<void>,
    ) => {
      if (isDisconnectingRef.current) return;
      isDisconnectingRef.current = true;
      const curCallId = callId;
      const curRoom = session?.room || "";

      let finalReason = callEndReasonRef.current;
      if (!finalReason) {
        if (
          selectedAgent?.agent_mode === "announcement" &&
          selectedAgent?.end_after_announcement
        ) {
          finalReason = "announcement_completed";
        } else if (
          reason === 5 ||
          String(reason).includes("5") ||
          String(reason).includes("ROOM_DELETED")
        ) {
          finalReason = "completed";
        } else if (
          reason === 7 ||
          String(reason).includes("7") ||
          String(reason).includes("JOIN_FAILURE")
        ) {
          finalReason = "connection_error";
        } else {
          finalReason = "room_disconnected";
        }
      }

      console.log(
        "[CALL_ENDED] room=" +
          curRoom +
          " call_id=" +
          curCallId +
          " reason=" +
          finalReason,
      );

      setCallState("ending");
      setTimeout(() => {
        replaceActiveSipCalls([]);
        setSession(null);
        setActiveMode(null);
        setCallState("ended");
        isDisconnectingRef.current = false;
        callEndReasonRef.current = null;
        void fetchCallSummary(curCallId);
      }, 250);
    },
    [callId, session],
  );

  return {
    callState,
    setCallState,
    session,
    setSession,
    callId,
    setCallId,
    busy,
    setBusy,
    err,
    setErr,
    agentWaitSeconds,
    isDisconnectingRef,
    callEndReasonRef,
    activeMode,
    activeSipCalls,
    updateActiveSipCall,
    removeActiveSipCall,
    finishSipCall,
    GoStart,
    endCurrentCall,
    // Backwards-compatible alias for older imports.
    endBrowserCall: endCurrentCall,
    handleAnnouncementFinished,
    handleRoomDisconnected,
  };
}
