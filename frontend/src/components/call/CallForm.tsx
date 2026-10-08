"use client";
import { Agent } from "@/lib/api";
import { CallState } from "./types";

/** Left column of the Call tab: agent picker, mode, SIP inputs, start/end. */
export default function CallForm({
  agents, agentsReady, agentId, onAgentSelect, selected,
  mode, onMode, phone, onPhone, trunkId, onTrunkId,
  busy, err, callEndedMsg, callState, isCallActive,
  session, callId, onGo, onEnd,
}: {
  agents: Agent[];
  agentsReady: boolean;
  agentId: string;
  onAgentSelect: (id: string) => void;
  selected?: Agent;
  mode: "browser" | "sip";
  onMode: (m: "browser" | "sip") => void;
  phone: string;
  onPhone: (v: string) => void;
  trunkId: string;
  onTrunkId: (v: string) => void;
  busy: boolean;
  err: string;
  callEndedMsg: string;
  callState: CallState;
  isCallActive: boolean;
  session: { room: string } | null;
  callId: string;
  onGo: () => void;
  onEnd: () => void;
}) {
  return (
    <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
      <h2 className="text-xl font-bold mb-4">⚡ Start a Call</h2>

      <label className="text-xs text-gray-400 font-medium">Agent</label>
      <select
        value={agentId}
        disabled={isCallActive}
        onChange={(e) => onAgentSelect(e.target.value)}
        className="input mt-1 mb-2"
      >
        {agentsReady ? (
          <option value="">Select an agent…</option>
        ) : (
          <option value="">Loading agents…</option>
        )}
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
          onClick={() => onMode("browser")}
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
          onClick={() => onMode("sip")}
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
              onChange={(e) => onPhone(e.target.value)}
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
              onChange={(e) => onTrunkId(e.target.value)}
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
      {err && callState === "error" && !session && agentId && (
        <button
          type="button"
          onClick={onGo}
          className="w-full mt-3 bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 rounded-xl transition-all"
        >
          🔄 Try Again
        </button>
      )}
      {callEndedMsg && !callEndedMsg.startsWith("Finalizing") && !err && (
        <div className="text-green-300 text-sm bg-green-500/10 border border-green-500/30 rounded-lg p-3 mt-4">
          {callEndedMsg}
        </div>
      )}

      <button
        onClick={onGo}
        disabled={busy || isCallActive || !agentId || !agentsReady}
        className="w-full bg-green-600 hover:bg-green-500 text-white font-bold text-lg py-3 rounded-xl mt-4 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
      >
        {!agentsReady && callState === "idle" && !isCallActive
            ? "Loading agents..."
            : busy || callState === "connecting"
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
          onClick={onEnd}
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
  );
}
