"use client";
import { MutableRefObject } from "react";
import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import ActiveSession from "./ActiveSession";
import { Agent, CallState, STATIC_AUDIO_OPTIONS } from "./types";

/**
 * Right column of the Call tab: the LiveKit room (in-call UI) when a session
 * exists, otherwise the idle / last-call / error placeholders.
 */
export default function RoomStage({
  session, callState, isDisconnectingRef, selected, callId, mode, err,
  callEndedMsg, agentWaitSeconds, onRoomDisconnected, onStateChange,
  onAnnouncementFinished,
}: {
  session: { token: string; url: string; room: string } | null;
  callState: CallState;
  isDisconnectingRef: MutableRefObject<boolean>;
  selected?: Agent;
  callId: string;
  mode: "browser" | "sip";
  err: string;
  callEndedMsg: string;
  agentWaitSeconds: number;
  onRoomDisconnected: (reason?: unknown) => void;
  onStateChange: (st: CallState) => void;
  onAnnouncementFinished: () => void;
}) {
  return (
    <div className="flex items-center justify-center bg-gray-900 rounded-2xl border border-gray-800 min-h-[380px] p-4">
      {session ? (
        <LiveKitRoom
          token={session.token}
          serverUrl={session.url}
          connect={!isDisconnectingRef.current && (callState === "connecting" || callState === "waiting_for_agent" || callState === "connected")}
          audio={STATIC_AUDIO_OPTIONS}
          video={false}
          onDisconnected={onRoomDisconnected}
          onError={(error) => {
            console.error(`[CALL_ERROR] LiveKitRoom error: ${error?.message || error}`);
          }}
          className="w-full flex items-center justify-center"
        >
          <ActiveSession
            agent={selected}
            callId={callId}
            roomName={session.room}
            onStateChange={onStateChange}
            onAnnouncementFinished={onAnnouncementFinished}
            waitSeconds={agentWaitSeconds}
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
  );
}
