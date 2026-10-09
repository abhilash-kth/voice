"use client";

import {
  PhoneCall,
  AlertTriangle,
  CheckCircle2,
  Monitor,
  Phone,
} from "lucide-react";
import type { Agent } from "@/lib/api";
import type { CallState } from "../types/call-types";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import LiveCallRoom, { type LiveCallSession } from "./LiveCallRoom";

interface CallStageProps {
  session: LiveCallSession | null;
  callState: CallState;
  callEndedMsg: string;
  err: string;
  mode: "browser" | "sip";
  selected?: Agent;
  callId: string;
  agentWaitSeconds: number;
  isDisconnecting: boolean;
  onStateChange: (state: CallState) => void;
  onAnnouncementFinished: () => void;
  onDisconnected: (reason?: unknown) => void;
}

export default function CallStage({
  session,
  callState,
  callEndedMsg,
  err,
  mode,
  selected,
  callId,
  agentWaitSeconds,
  isDisconnecting,
  onStateChange,
  onAnnouncementFinished,
  onDisconnected,
}: CallStageProps) {
  return (
    <Card
      className={cn(
        "flex min-h-[380px] items-center justify-center border-border/60 py-0 shadow-sm",
        "bg-card",
      )}
    >
      <div className="flex w-full items-center justify-center p-4 sm:p-6">
        {session ? (
          <LiveCallRoom
            session={session}
            agent={selected}
            callId={callId}
            callState={callState}
            isDisconnecting={isDisconnecting}
            waitSeconds={agentWaitSeconds}
            onStateChange={onStateChange}
            onAnnouncementFinished={onAnnouncementFinished}
            onDisconnected={onDisconnected}
          />
        ) : (
          <EmptyStage
            callState={callState}
            callEndedMsg={callEndedMsg}
            err={err}
            mode={mode}
          />
        )}
      </div>
    </Card>
  );
}

function EmptyStage({
  callState,
  callEndedMsg,
  err,
  mode,
}: {
  callState: CallState;
  callEndedMsg: string;
  err: string;
  mode: "browser" | "sip";
}) {
  if (callEndedMsg) {
    return (
      <div className="mx-auto max-w-sm space-y-3 px-4 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="h-7 w-7" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">
            Last call ended
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {callEndedMsg}
          </p>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Start a new call from the panel on the left.
        </p>
      </div>
    );
  }

  if (callState === "error") {
    return (
      <div className="mx-auto max-w-sm space-y-3 px-4 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-destructive/20 bg-destructive/10 text-destructive">
          <AlertTriangle className="h-7 w-7" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-semibold text-destructive">Call error</p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {err || "An error occurred"}
          </p>
        </div>
      </div>
    );
  }

  if (mode === "browser") {
    return (
      <div className="mx-auto max-w-sm space-y-3 px-4 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-border/60 bg-muted/40 text-muted-foreground">
          <Monitor className="h-7 w-7" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">
            Ready for a voice call
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Select an agent, then press{" "}
            <span className="font-medium text-foreground">
              Start voice call
            </span>
            . Your microphone will be used in this browser.
          </p>
        </div>
        <div className="flex items-center justify-center gap-1.5 text-[11px] text-muted-foreground">
          <PhoneCall className="h-3 w-3" />
          LiveKit · WebRTC
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm space-y-3 px-4 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-border/60 bg-muted/40 text-muted-foreground">
        <Phone className="h-7 w-7" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">Ready to dial</p>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Enter an E.164 number, then press{" "}
          <span className="font-medium text-foreground">Dial number</span>. The
          agent will place a real SIP call.
        </p>
      </div>
    </div>
  );
}
