import { useRef, useState } from "react";
import { getCall } from "@/lib";
import { CallState } from "../types/call-types";

type UseCallSummaryProps = {
  onStarted: () => void;
  setCallState: (state: CallState) => void;
  setErr: (message: string) => void;
};

export default function useCallSummary({
  onStarted,
  setCallState,
  setErr,
}: UseCallSummaryProps) {
  // Holds the message shown after a call ends and invalidates stale polling.
  const [callEndedMsg, setCallEndedMsg] = useState("");
  const activeSummaryPollRef = useRef(0);

  // Clears the previous result and stops its poll from updating this call.
  const clearCallSummary = () => {
    activeSummaryPollRef.current += 1;
    setCallEndedMsg("");
  };

  // Waits for finalized billing data, then shows the call result.
  const fetchCallSummary = async (cid: string) => {
    if (!cid) {
      setCallEndedMsg("Call ended. Select an agent to start a new call.");
      return;
    }

    const pollId = ++activeSummaryPollRef.current;
    setCallEndedMsg("Finalizing call & calculating billing summary…");

    // Poll until billing is finalized and written to DB (up to 12s).
    let attempts = 0;
    const maxAttempts = 12;
    while (attempts < maxAttempts) {
      if (activeSummaryPollRef.current !== pollId) return;
      try {
        await new Promise((resolve) =>
          setTimeout(resolve, attempts === 0 ? 800 : 1200),
        );
        if (activeSummaryPollRef.current !== pollId) return;
        attempts++;
        const call = await getCall(cid);
        if (activeSummaryPollRef.current !== pollId) return;

        if (call.status === "failed") {
          const reason =
            (typeof call.usage === "object" &&
              call.usage !== null &&
              (call.usage as any).error) ||
            "the agent worker could not start the call";
          setCallEndedMsg("");
          setErr("Call failed: " + reason);
          setCallState("error");
          onStarted();
          return;
        }

        const costInr = (call.cost as any)?.client_price_inr;
        const duration = call.duration_seconds ?? 0;
        const isFinalized =
          call.status === "completed" || call.status === "failed";

        if (
          costInr !== undefined &&
          costInr !== null &&
          (Number(costInr) > 0 || duration > 0)
        ) {
          setCallEndedMsg(
            "Call completed • " +
              duration +
              "s • Billed ₹" +
              (Number(costInr) || 0).toFixed(2) +
              " • Wallet balance updated",
          );
          onStarted();
          return;
        }

        if (isFinalized && duration > 0) {
          setCallEndedMsg(
            "Call completed • " +
              duration +
              "s • Billed ₹" +
              Number(costInr || 0).toFixed(2) +
              " • Wallet balance updated",
          );
          onStarted();
          return;
        }
      } catch {
        // Continue polling if the backend is temporarily unavailable.
      }
    }

    if (activeSummaryPollRef.current !== pollId) return;
    try {
      const call = await getCall(cid);
      if (activeSummaryPollRef.current !== pollId) return;
      const costInr = Number((call.cost as any)?.client_price_inr || 0);
      const duration = call.duration_seconds ?? 0;
      setCallEndedMsg(
        "Call completed • " +
          duration +
          "s • Billed ₹" +
          costInr.toFixed(2) +
          " • Wallet balance updated",
      );
      onStarted();
    } catch {
      if (activeSummaryPollRef.current === pollId) {
        setCallEndedMsg("Call ended. Select an agent to start a new call.");
      }
    }
  };

  return {
    callEndedMsg,
    setCallEndedMsg,
    activeSummaryPollRef,
    clearCallSummary,
    fetchCallSummary,
  };
}
