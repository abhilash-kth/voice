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

export default function useCallSession() {
  // Stores the current call state and LiveKit connection data.
  const [callState, setCallState] = useState<CallState>("idle");
  const [session, setSession] = useState<{
    token: string;
    url: string;
    room: string;
  } | null>(null);
  const [callId, setCallId] = useState("");

  // Tracks start progress, user-facing errors, and agent wait time.
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [agentWaitSeconds, setAgentWaitSeconds] = useState(0);

  // Refs prevent duplicate disconnect handling and remember the end reason.
  const isDisconnectingRef = useRef(false);
  const callEndReasonRef = useRef<string | null>(null);

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
  async function GoStart(options: StartCallProps) {
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
    if (!selectedAgent) return setErr("Selected agent not found.");
    if (mode === "sip" && !phone)
      return setErr("Enter a phone number for SIP calling.");

    console.log(`[CALL_START] agent_id=${agentId} mode=${mode}`);
    console.log(
      `[AGENT_SELECTED] agent_id=${agentId} name=${selectedAgent.name} mode=${selectedAgent.agent_mode || "assistant"}`,
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
  }

  // Ends the active call and starts summary polling after cleanup.
  async function endBrowserCall(fetchCallSummary: (callId: string) => Promise<void>) {
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
        setSession(null);
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
        setSession(null);
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
    GoStart,
    endBrowserCall,
    handleAnnouncementFinished,
    handleRoomDisconnected,
  };
}
