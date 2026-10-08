"use client";
import { useEffect, useRef, useState } from "react";
import {
  VoiceAssistantControlBar,
  StartAudio,
  useVoiceAssistant,
  BarVisualizer,
  useRoomContext,
  useParticipants,
} from "@livekit/components-react";
import { Agent, CallState } from "./types";

/**
 * The in-call UI inside a connected LiveKit room: voice-orb state,
 * announcement completion tracking, participant/agent-join logs.
 */
export default function ActiveSession({
  agent,
  callId,
  roomName,
  onStateChange,
  onAnnouncementFinished,
  waitSeconds,
}: {
  agent?: Agent;
  callId: string;
  roomName: string;
  onStateChange: (state: CallState) => void;
  onAnnouncementFinished: () => void;
  waitSeconds: number;
}) {
  const room = useRoomContext();
  const { state: vaState, audioTrack } = useVoiceAssistant();
  const participants = useParticipants();
  const [agentJoined, setAgentJoined] = useState(false);
  const [waitingLogged, setWaitingLogged] = useState(false);
  const announcementSpokeRef = useRef(false);
  const announcementFinishedRef = useRef(false);
  const [announcementDone, setAnnouncementDone] = useState(false);

  // Auto-start browser audio playout once room is connected
  useEffect(() => {
    if (room.state === "connected") {
      room.startAudio().catch(() => {});
    }
  }, [room, room.state]);

  // Track room connection and mic publication
  useEffect(() => {
    if (room.state === "connected") {
      console.log(`[LIVEKIT_CONNECTED] room=${roomName}`);
      console.log(`[MIC_PUBLISHED] room=${roomName}`);
    }
  }, [room.state, roomName]);

  // Monitor participants for the remote agent
  useEffect(() => {
    const remoteAgents = participants.filter((p) => !p.isLocal);
    if (remoteAgents.length > 0 && !agentJoined) {
      setAgentJoined(true);
      onStateChange("connected");
      const remote = remoteAgents[0];
      console.log(`[AGENT_JOINED] room=${roomName} identity=${remote.identity}`);
      console.log(
        `[AGENT_STARTED] room=${roomName} agent_id=${agent?.id || ""} mode=${agent?.agent_mode || "assistant"}`
      );
      if (agent?.agent_mode === "announcement") {
        console.log(`[ANNOUNCEMENT_STARTED] room=${roomName}`);
      } else {
        console.log(`[ASSISTANT_STARTED] room=${roomName}`);
      }
    } else if (remoteAgents.length === 0 && !agentJoined && !waitingLogged) {
      setWaitingLogged(true);
      console.log(`[AGENT_WAITING] room=${roomName} agent_id=${agent?.id || ""}`);
    }
  }, [participants, agentJoined, roomName, agent, waitingLogged, onStateChange]);

  // Track announcement playback state
  useEffect(() => {
    if (agent?.agent_mode === "announcement") {
      if (vaState === "speaking") {
        announcementSpokeRef.current = true;
      } else if (
        announcementSpokeRef.current &&
        !announcementFinishedRef.current &&
        (vaState === "idle" || vaState === "listening")
      ) {
        announcementFinishedRef.current = true;
        setAnnouncementDone(true);
        console.log(`[ANNOUNCEMENT_FINISHED] room=${roomName}`);
        onAnnouncementFinished();
      }
    }
  }, [vaState, agent, roomName, onAnnouncementFinished]);

  return (
    <div className="flex flex-col items-center gap-6 p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl max-w-md w-full animate-fade-in-up">
      <div
        className={`w-36 h-36 rounded-full flex items-center justify-center text-6xl transition-all duration-300 ${
          vaState === "speaking"
            ? "bg-green-500 animate-pulse shadow-lg shadow-green-500/50"
            : vaState === "listening"
              ? "bg-blue-500 shadow-lg shadow-blue-500/50"
              : vaState === "thinking"
                ? "bg-yellow-500 shadow-lg shadow-yellow-500/30 animate-pulse"
                : !agentJoined
                  ? "bg-amber-600 animate-pulse"
                  : announcementDone
                    ? "bg-indigo-600 shadow-lg shadow-indigo-500/30"
                    : "bg-gray-700"
        }`}
      >
        {vaState === "speaking"
          ? "🗣️"
          : vaState === "listening"
            ? "👂"
            : vaState === "thinking"
              ? "💭"
              : !agentJoined
                ? "⏳"
                : announcementDone
                  ? "📢"
                  : "🤖"}
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-1">
          {agent?.name || "Live Agent"}
        </h2>
        <p className="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-1">
          {agent?.agent_mode === "announcement"
            ? "📢 Announcement Mode"
            : "🎙️ Conversational Assistant"}
        </p>
        <p className="text-gray-300 text-sm font-medium">
          {!agentJoined
            ? `Waiting for agent to connect… ${waitSeconds}s`
            : vaState === "speaking"
              ? agent?.agent_mode === "announcement"
                ? "Playing announcement script..."
                : "Agent is speaking..."
              : announcementDone
                ? "Announcement completed. Call is active."
                : vaState === "listening"
                  ? "Listening to you..."
                  : vaState === "thinking"
                    ? "Thinking..."
                    : "Connected to agent"}
        </p>
        <p className="text-[11px] text-gray-500 mt-1">
          {participants.length} participant{participants.length !== 1 ? "s" : ""} in room
          {announcementDone && " • You can stay connected or press End Call"}
        </p>
      </div>

      {audioTrack && (
        <div className="w-full h-16">
          <BarVisualizer
            state={vaState}
            barCount={24}
            trackRef={audioTrack}
            className="h-full w-full"
          />
        </div>
      )}

      <StartAudio
        label="Click if audio is muted"
        className="mt-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-black px-4 py-1.5 text-xs font-semibold cursor-pointer"
      />

      <VoiceAssistantControlBar controls={{ leave: false, microphone: true }} />
    </div>
  );
}
