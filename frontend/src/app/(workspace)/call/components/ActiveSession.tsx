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
import "@livekit/components-styles";
import {
  Bot,
  Ear,
  Loader2,
  Megaphone,
  MessageSquare,
  Sparkles,
  Volume2,
} from "lucide-react";
import { Agent } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { CallState } from "../types/call-types";

interface ActiveSessionProps {
  agent?: Agent;
  callId: string;
  roomName: string;
  onStateChange: (state: CallState) => void;
  onAnnouncementFinished: () => void;
  waitSeconds: number;
}

export default function ActiveSession({
  agent,
  callId,
  roomName,
  onStateChange,
  onAnnouncementFinished,
  waitSeconds,
}: ActiveSessionProps) {
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
      console.log(
        `[AGENT_JOINED] room=${roomName} identity=${remote.identity}`,
      );
      console.log(
        `[AGENT_STARTED] room=${roomName} agent_id=${agent?.id || ""} mode=${agent?.agent_mode || "assistant"}`,
      );
      if (agent?.agent_mode === "announcement") {
        console.log(`[ANNOUNCEMENT_STARTED] room=${roomName}`);
      } else {
        console.log(`[ASSISTANT_STARTED] room=${roomName}`);
      }
    } else if (remoteAgents.length === 0 && !agentJoined && !waitingLogged) {
      setWaitingLogged(true);
      console.log(
        `[AGENT_WAITING] room=${roomName} agent_id=${agent?.id || ""}`,
      );
    }
  }, [
    participants,
    agentJoined,
    roomName,
    agent,
    waitingLogged,
    onStateChange,
  ]);

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

  const isAnnouncement = agent?.agent_mode === "announcement";

  const statusLabel = !agentJoined
    ? `Waiting for agent… ${waitSeconds}s`
    : vaState === "speaking"
      ? isAnnouncement
        ? "Playing announcement…"
        : "Agent is speaking…"
      : announcementDone
        ? "Announcement complete — call still active"
        : vaState === "listening"
          ? "Listening to you…"
          : vaState === "thinking"
            ? "Thinking…"
            : "Connected";

  const StatusIcon = !agentJoined
    ? Loader2
    : vaState === "speaking"
      ? Volume2
      : vaState === "listening"
        ? Ear
        : vaState === "thinking"
          ? Sparkles
          : announcementDone
            ? Megaphone
            : Bot;

  return (
    <Card className="flex w-full max-w-md flex-col items-center gap-6 border-border/60 bg-card py-0 shadow-sm">
      <div className="flex w-full flex-col items-center gap-6 p-6 sm:p-8">
        {/* Status orb */}
        <div
          className={cn(
            "relative flex h-28 w-28 items-center justify-center rounded-full border transition-all duration-300",
            vaState === "speaking" &&
              "border-emerald-500/40 bg-emerald-500/15 text-emerald-600 shadow-[0_0_32px_-8px] shadow-emerald-500/40 dark:text-emerald-400",
            vaState === "listening" &&
              "border-blue-500/40 bg-blue-500/15 text-blue-600 shadow-[0_0_32px_-8px] shadow-blue-500/40 dark:text-blue-400",
            vaState === "thinking" &&
              "border-amber-500/40 bg-amber-500/15 text-amber-600 shadow-[0_0_32px_-8px] shadow-amber-500/30 dark:text-amber-400",
            !agentJoined &&
              "border-amber-500/30 bg-amber-500/10 text-amber-600 animate-pulse dark:text-amber-400",
            agentJoined &&
              announcementDone &&
              vaState !== "speaking" &&
              vaState !== "listening" &&
              vaState !== "thinking" &&
              "border-primary/30 bg-primary/10 text-primary",
            agentJoined &&
              !announcementDone &&
              vaState !== "speaking" &&
              vaState !== "listening" &&
              vaState !== "thinking" &&
              "border-border bg-muted text-muted-foreground",
          )}
        >
          {(vaState === "speaking" || !agentJoined) && (
            <span
              className={cn(
                "absolute inset-0 rounded-full opacity-40",
                vaState === "speaking" ? "bg-emerald-500/20 animate-ping" : "",
                !agentJoined ? "bg-amber-500/10" : "",
              )}
            />
          )}
          <StatusIcon
            className={cn("relative h-10 w-10", !agentJoined && "animate-spin")}
          />
        </div>

        {/* Identity + status copy */}
        <div className="space-y-2 text-center">
          <h2 className="text-xl font-bold tracking-tight text-foreground">
            {agent?.name || "Live Agent"}
          </h2>

          <div className="flex justify-center">
            <Badge
              variant="outline"
              className={cn(
                "h-6 gap-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-wider",
                isAnnouncement
                  ? "border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-400"
                  : "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
              )}
            >
              {isAnnouncement ? (
                <Megaphone className="h-3 w-3" />
              ) : (
                <MessageSquare className="h-3 w-3" />
              )}
              {isAnnouncement ? "Announcement" : "Assistant"}
            </Badge>
          </div>

          <p className="text-sm font-medium text-foreground">{statusLabel}</p>
          <p className="text-[11px] text-muted-foreground">
            {participants.length} participant
            {participants.length !== 1 ? "s" : ""} in room
            {announcementDone ? " · Stay connected or end the call" : null}
          </p>
        </div>

        {/* Visualizer */}
        {audioTrack && (
          <div className="h-14 w-full overflow-hidden rounded-lg border border-border/60 bg-muted/30 px-2 py-1.5">
            <BarVisualizer
              state={vaState}
              barCount={24}
              trackRef={audioTrack}
              className="h-full w-full"
            />
          </div>
        )}

        {/* LiveKit controls */}
        <div className="flex w-full flex-col items-center gap-3">
          <StartAudio
            label="Click if audio is muted"
            className="cursor-pointer rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-800 transition-colors hover:bg-amber-500/20 dark:text-amber-300"
          />
          <div className="w-full [&_.lk-button]:rounded-md [&_.lk-button]:border-border [&_.lk-button]:bg-background">
            <VoiceAssistantControlBar
              controls={{ leave: false, microphone: true }}
            />
          </div>
        </div>
      </div>
    </Card>
  );
}
