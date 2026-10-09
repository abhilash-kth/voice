"use client";

import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import "@livekit/components-styles";
import type { Agent } from "@/lib/api";
import type { CallState } from "../types/call-types";
import ActiveSession from "./ActiveSession";

export interface LiveCallSession {
  token: string;
  url: string;
  room: string;
}

interface LiveCallRoomProps {
  session: LiveCallSession;
  agent?: Agent;
  callId: string;
  callState: CallState;
  /** When true, LiveKit should not try to (re)connect */
  isDisconnecting: boolean;
  waitSeconds: number;
  onStateChange: (state: CallState) => void;
  onAnnouncementFinished: () => void;
  onDisconnected: (reason?: unknown) => void;
}

export default function LiveCallRoom({
  session,
  agent,
  callId,
  callState,
  isDisconnecting,
  waitSeconds,
  onStateChange,
  onAnnouncementFinished,
  onDisconnected,
}: LiveCallRoomProps) {
  const shouldConnect =
    !isDisconnecting &&
    (callState === "connecting" ||
      callState === "waiting_for_agent" ||
      callState === "connected");

  return (
    <LiveKitRoom
      token={session.token}
      serverUrl={session.url}
      connect={shouldConnect}
      audio={{
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }}
      video={false}
      onDisconnected={onDisconnected}
      onError={(error) => {
        console.error(
          `[CALL_ERROR] LiveKitRoom error: ${error?.message || error}`,
        );
      }}
      className="flex w-full items-center justify-center"
    >
      <ActiveSession
        agent={agent}
        callId={callId}
        roomName={session.room}
        onStateChange={onStateChange}
        onAnnouncementFinished={onAnnouncementFinished}
        waitSeconds={waitSeconds}
      />
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}
