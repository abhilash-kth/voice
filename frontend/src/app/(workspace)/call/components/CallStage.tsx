"use client";

import {
  PhoneCall,
  AlertTriangle,
  CheckCircle2,
  Monitor,
  Phone,
} from "lucide-react";
import type { Agent } from "@/lib/index";
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
        "flex min-h-[440px] items-stretch justify-center overflow-hidden border-border/60 bg-card p-0 shadow-sm xl:min-h-[560px]",
      )}
    >
      <div className="relative flex w-full flex-1 items-center justify-center bg-[radial-gradient(ellipse_at_top,var(--tw-gradient-stops))] from-primary/10 via-background to-background p-5 sm:p-8">
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
      <div className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-600 shadow-sm dark:text-emerald-400">
          <CheckCircle2 className="h-7 w-7" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold tracking-tight text-foreground">
            Last call ended
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {callEndedMsg}
          </p>
        </div>
        <p className="rounded-full border border-border/70 bg-background/80 px-3 py-1.5 text-xs text-muted-foreground">
          Start a new call from the panel on the left.
        </p>
      </div>
    );
  }

  if (callState === "error") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-destructive/20 bg-destructive/10 text-destructive shadow-sm">
          <AlertTriangle className="h-7 w-7" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold tracking-tight text-destructive">
            Call error
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {err || "An error occurred"}
          </p>
        </div>
      </div>
    );
  }

  if (
    mode === "sip" &&
    (callState === "connecting" ||
      callState === "connected" ||
      callState === "ending")
  ) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-600 shadow-sm dark:text-emerald-400">
          <PhoneCall className="h-7 w-7 animate-pulse" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold tracking-tight text-foreground">
            {callState === "ending"
              ? "Ending SIP call"
              : callState === "connecting"
                ? "Dialing SIP call"
                : "SIP call in progress"}
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            The agent is connected through the phone network. Hang up on the
            phone or use <span className="font-medium text-foreground">End call</span>{" "}
            on the left; this screen updates automatically when the call ends.
          </p>
        </div>
        <div className="flex items-center justify-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/5 px-3 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          Live phone call
        </div>
      </div>
    );
  }

  if (mode === "browser") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary shadow-sm">
          <Monitor className="h-7 w-7" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold tracking-tight text-foreground">
            Ready for a voice call
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Select an agent, then press{" "}
            <span className="font-medium text-foreground">
              Start voice call
            </span>
            . Your microphone will be used in this browser.
          </p>
        </div>
        <div className="flex items-center justify-center gap-2 rounded-full border border-border/70 bg-background/80 px-3 py-1.5 text-xs text-muted-foreground">
          <PhoneCall className="h-3 w-3" />
          LiveKit · WebRTC
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary shadow-sm">
        <Phone className="h-7 w-7" />
      </div>
      <div className="space-y-2">
        <p className="text-lg font-semibold tracking-tight text-foreground">
          Ready to dial
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Enter an E.164 number, then press{" "}
          <span className="font-medium text-foreground">Dial number</span>. The
          agent will place a real SIP call.
        </p>
      </div>
    </div>
  );
}
