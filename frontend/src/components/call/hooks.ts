"use client";
// Call-panel hooks (moved out of CallPanel; ≤300-line rule):
//   useJoinWatchdog  – fails the call if the agent never joins (30s) or the
//                      backend marks it failed, with the REAL reason
//   useLastAgent     – agent preselect: preset > localStorage > first agent
//   useCallSummary   – post-call billing-summary poller
import { useCallback, useEffect, useRef, useState } from "react";
import { Agent, getCall, endCall } from "@/lib/api";
import { CallState, LAST_AGENT_KEY } from "./types";

/**
 * While callState === "waiting_for_agent": ticks a seconds counter, watches
 * the backend record for a failed status, and calls onFail(message) on the
 * hard 30s join timeout (worker stopped/busy).
 */
export function useJoinWatchdog({
  callState, callId, isDisconnectingRef, onFail,
}: {
  callState: CallState;
  callId: string;
  isDisconnectingRef: React.MutableRefObject<boolean>;
  onFail: (message: string) => void;
}) {
  const [agentWaitSeconds, setAgentWaitSeconds] = useState(0);
  const onFailRef = useRef(onFail);
  onFailRef.current = onFail;

  useEffect(() => {
    if (callState !== "waiting_for_agent" || !callId) return;
    const startedAt = Date.now();
    let cancelled = false;

    const failWait = async (message: string) => {
      if (cancelled) return;
      console.error(`[CALL_ERROR] agent_join_failed: ${message}`);
      onFailRef.current(message);
      isDisconnectingRef.current = true; // suppress handleRoomDisconnected takeover
      try {
        await endCall(callId); // release the room so "Try again" starts clean
      } catch {
        /* backend error on cleanup is fine — the state reset below still works */
      }
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
            (typeof c.usage === "object" && c.usage !== null && (c.usage as any).error) ||
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
  }, [callState, callId, isDisconnectingRef]);

  return agentWaitSeconds;
}

/** Agent preselection: explicit preset > last-chosen localStorage > first. */
export function useLastAgent({
  agents, presetAgentId, agentId, setAgentId, onPresetConsumed,
}: {
  agents: Agent[];
  presetAgentId?: string;
  agentId: string;
  setAgentId: (id: string) => void;
  onPresetConsumed?: () => void;
}) {
  useEffect(() => {
    if (!agents.length) return;

    if (presetAgentId && agents.some((a) => a.id === presetAgentId)) {
      setAgentId(presetAgentId);
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(LAST_AGENT_KEY, presetAgentId);
        } catch {}
      }
      onPresetConsumed?.();
      return;
    }

    if (agentId && agents.some((a) => a.id === agentId)) {
      return;
    }

    let savedAgentId: string | null = null;
    if (typeof window !== "undefined") {
      try {
        savedAgentId = localStorage.getItem(LAST_AGENT_KEY);
      } catch {}
    }

    if (savedAgentId && agents.some((a) => a.id === savedAgentId)) {
      setAgentId(savedAgentId);
    } else {
      const fallbackId = agents[0].id;
      setAgentId(fallbackId);
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(LAST_AGENT_KEY, fallbackId);
        } catch {}
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, presetAgentId, agentId, onPresetConsumed]);
}

/**
 * Post-call billing summary: polls the call record until the worker-settled
 * price is written (up to 12s), then reports the final message. A newer
 * poll supersedes an older one (guard token).
 */
export function useCallSummary({
  onMessage, onError, onRefresh,
}: {
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
  onRefresh: () => void;
}) {
  const activeSummaryPollRef = useRef<number>(0);
  const refreshRef = useRef({ onMessage, onError, onRefresh });
  refreshRef.current = { onMessage, onError, onRefresh };

  const fetchCallSummary = useCallback(async (cid: string) => {
    const { onMessage, onError, onRefresh } = refreshRef.current;
    if (!cid) {
      onMessage("Call ended. Select an agent to start a new call.");
      return;
    }
    const pollId = ++activeSummaryPollRef.current;
    onMessage("Finalizing call & calculating billing summary…");
    const guard = () => activeSummaryPollRef.current === pollId;

    const report = (cost: number, duration: number) => {
      onMessage(
        `Call completed • ${duration}s • Billed ₹${Number(cost || 0).toFixed(2)} • Wallet balance updated`
      );
      onRefresh(); // triggers refreshWallet() and refreshAgents() in parent
    };

    // Poll until billing is finalized and written to DB (up to 12s)
    let attempts = 0;
    const maxAttempts = 12;
    while (attempts < maxAttempts) {
      if (!guard()) return;
      try {
        await new Promise((r) => setTimeout(r, attempts === 0 ? 800 : 1200));
        if (!guard()) return;
        attempts++;
        const c = await getCall(cid);
        if (!guard()) return;
        if (c.status === "failed") {
          // Surface the real reason instead of a fake "completed, billed ₹0.00".
          const why =
            (typeof c.usage === "object" && c.usage !== null && (c.usage as any).error) ||
            "the agent worker could not start the call";
          onError(`Call failed: ${why}`);
          onRefresh();
          return;
        }
        const costInr = (c.cost as any)?.client_price_inr;
        const duration = c.duration_seconds ?? 0;
        const isFinalized = c.status === "completed" || c.status === "failed";

        // Billing is ready once cost is posted or duration > 0.
        if (costInr !== undefined && costInr !== null && (Number(costInr) > 0 || duration > 0)) {
          report(Number(costInr) || 0, duration);
          return;
        }
        if (isFinalized && duration > 0) {
          report(Number(costInr || 0), duration);
          return;
        }
      } catch {
        // continue polling on error
      }
    }

    if (!guard()) return;
    // Final attempt fallback
    try {
      const c = await getCall(cid);
      if (!guard()) return;
      report(Number((c.cost as any)?.client_price_inr || 0), c.duration_seconds ?? 0);
    } catch {
      if (guard()) {
        onMessage("Call ended. Select an agent to start a new call.");
      }
    }
  }, []);

  return { fetchCallSummary, activeSummaryPollRef };
}

/** User pressing "End Call" (browser calls) — moved from CallPanel. */
export function useEndBrowserCall({
  isDisconnectingRef, callEndReasonRef, callId, sessionRoom,
  setCallState, setSession, fetchCallSummary,
}: {
  isDisconnectingRef: React.MutableRefObject<boolean>;
  callEndReasonRef: React.MutableRefObject<string | null>;
  callId: string;
  sessionRoom: string;
  setCallState: (s: CallState) => void;
  setSession: (s: null) => void;
  fetchCallSummary: (cid: string) => Promise<void>;
}) {
  return useCallback(async () => {
    if (isDisconnectingRef.current) return;
    isDisconnectingRef.current = true;
    callEndReasonRef.current = "user_ended";
    console.log(`[CALL_END_REQUESTED] source=user call_id=${callId}`);
    setCallState("ending");

    const curCallId = callId;
    const curRoom = sessionRoom || "";

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
  }, [isDisconnectingRef, callEndReasonRef, callId, sessionRoom,
      setCallState, setSession, fetchCallSummary]);
}
