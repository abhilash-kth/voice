"use client";

import {
  PhoneCall,
  Phone,
  Monitor,
  Loader2,
  RotateCcw,
  PhoneOff,
  Bot,
  Info,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { Agent } from "@/lib/index";
import type { CallState } from "../types/call-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export interface CallSessionInfo {
  token: string;
  url: string;
  room: string;
}

export interface CallSetupFormProps {
  agents: Agent[];
  agentsReady: boolean;
  agentId: string;
  selected: Agent | undefined;
  onAgentChange: (id: string) => void;

  mode: "browser" | "sip";
  onModeChange: (mode: "browser" | "sip") => void;
  phone: string;
  onPhoneChange: (value: string) => void;
  trunkId: string;
  onTrunkChange: (value: string) => void;

  busy: boolean;
  err: string;
  callState: CallState;
  callEndedMsg: string;
  isCallActive: boolean;
  session: CallSessionInfo | null;
  callId: string;

  onStart: () => void;
  onEnd: () => void;
}

export default function CallSetupForm({
  agents,
  agentsReady,
  agentId,
  selected,
  onAgentChange,
  mode,
  onModeChange,
  phone,
  onPhoneChange,
  trunkId,
  onTrunkChange,
  busy,
  err,
  callState,
  callEndedMsg,
  isCallActive,
  session,
  callId,
  onStart,
  onEnd,
}: CallSetupFormProps) {
  const startLabel =
    !agentsReady && callState === "idle" && !isCallActive
      ? "Loading agents…"
      : busy || callState === "connecting"
        ? "Connecting…"
        : callState === "waiting_for_agent"
          ? "Waiting for agent…"
          : isCallActive
            ? "Call connected"
            : mode === "browser"
              ? "Start voice call"
              : "Dial number";

  const startPending =
    busy ||
    callState === "connecting" ||
    callState === "waiting_for_agent" ||
    (!agentsReady && callState === "idle");

  return (
    <Card className="border-border/60 py-0 shadow-sm">
      <div className="flex flex-col gap-5 p-5 sm:p-6">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <PhoneCall className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Start a call
            </h2>
            <p className="text-xs text-muted-foreground">
              Choose an agent and connect in the browser or via SIP.
            </p>
          </div>
        </div>

        <Separator className="bg-border/60" />

        {/* Agent */}
        <div className="space-y-1.5">
          <Label
            htmlFor="call-agent"
            className="text-xs font-medium text-muted-foreground"
          >
            Agent
          </Label>
          <div className="relative">
            <Bot className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <select
              id="call-agent"
              value={agentId}
              disabled={isCallActive}
              onChange={(e) => onAgentChange(e.target.value)}
              className={cn(
                "flex h-9 w-full appearance-none rounded-md border border-input bg-background py-1 pl-9 pr-8 text-sm shadow-sm transition-colors",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {agentsReady ? (
                <option value="">Select an agent…</option>
              ) : (
                <option value="">Loading agents…</option>
              )}
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} —{" "}
                  {a.agent_mode === "announcement"
                    ? "Announcement"
                    : "Assistant"}
                </option>
              ))}
            </select>
          </div>

          {selected ? (
            <div className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {selected.agent_mode === "announcement"
                  ? selected.end_after_announcement
                    ? "Announcement mode: plays a fixed script, then ends the call automatically."
                    : "Announcement mode: plays a fixed script and stays open until you end the call."
                  : "Assistant mode: greets on connect, then listens and converses turn by turn."}
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              Create an agent first, then select it here. The call uses only the
              agent you pick.
            </p>
          )}
        </div>

        {/* Mode */}
        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Call mode
          </Label>
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-border/60 bg-muted/40 p-1">
            <button
              type="button"
              disabled={isCallActive}
              onClick={() => onModeChange("browser")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-2 rounded-md text-xs font-semibold transition-all disabled:opacity-50",
                mode === "browser"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Monitor className="h-3.5 w-3.5" />
              Browser
              <Badge
                variant="secondary"
                className="h-5 px-1.5 text-[9px] font-semibold uppercase tracking-wide"
              >
                Free
              </Badge>
            </button>
            <button
              type="button"
              disabled={isCallActive}
              onClick={() => onModeChange("sip")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-2 rounded-md text-xs font-semibold transition-all disabled:opacity-50",
                mode === "sip"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Phone className="h-3.5 w-3.5" />
              SIP phone
            </button>
          </div>
        </div>

        {/* SIP fields */}
        {mode === "sip" && (
          <div className="space-y-3 rounded-lg border border-border/60 bg-muted/15 p-3.5">
            <div className="space-y-1.5">
              <Label
                htmlFor="call-phone"
                className="text-xs font-medium text-muted-foreground"
              >
                Phone number
                <span className="ml-1 font-normal text-muted-foreground/70">
                  (E.164)
                </span>
              </Label>
              <Input
                id="call-phone"
                value={phone}
                onChange={(e) => onPhoneChange(e.target.value)}
                placeholder="+91804xxxxxxx"
                className="h-9 font-mono text-sm"
                disabled={isCallActive}
                autoComplete="tel"
              />
            </div>
            <div className="space-y-1.5">
              <Label
                htmlFor="call-trunk"
                className="text-xs font-medium text-muted-foreground"
              >
                SIP trunk ID
                <span className="ml-1 font-normal text-muted-foreground/70">
                  (optional)
                </span>
              </Label>
              <Input
                id="call-trunk"
                value={trunkId}
                onChange={(e) => onTrunkChange(e.target.value)}
                placeholder="Trunk ID registered in LiveKit"
                className="h-9 font-mono text-sm"
                disabled={isCallActive}
              />
            </div>
            <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <Info className="mt-0.5 h-3 w-3 shrink-0" />
              Requires a LiveKit SIP trunk and carrier credentials on the
              backend.
            </p>
          </div>
        )}

        {/* Error */}
        {err && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="leading-snug">{err}</span>
          </div>
        )}

        {err && callState === "error" && !session && agentId && (
          <Button
            type="button"
            variant="outline"
            className="h-9 w-full gap-2"
            onClick={onStart}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Try again
          </Button>
        )}

        {/* Success / ended summary */}
        {callEndedMsg && !callEndedMsg.startsWith("Finalizing") && !err && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="leading-snug">{callEndedMsg}</span>
          </div>
        )}

        {/* Primary actions */}
        <div className="space-y-2 pt-1">
          <Button
            type="button"
            className="h-10 w-full gap-2 text-sm font-semibold"
            onClick={onStart}
            disabled={busy || isCallActive || !agentId || !agentsReady}
          >
            {startPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : mode === "browser" ? (
              <PhoneCall className="h-4 w-4" />
            ) : (
              <Phone className="h-4 w-4" />
            )}
            {startLabel}
          </Button>

          {isCallActive && (
            <Button
              type="button"
              variant="destructive"
              className="h-10 w-full gap-2 text-sm font-semibold"
              onClick={onEnd}
              disabled={callState === "ending"}
            >
              {callState === "ending" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <PhoneOff className="h-4 w-4" />
              )}
              {callState === "ending" ? "Ending call…" : "End call"}
            </Button>
          )}
        </div>

        {/* Session meta */}
        {mode === "browser" && session && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 font-mono text-[11px] text-muted-foreground">
            <span className="text-foreground/80">Room</span> {session.room}
            <span className="mx-1.5 text-border">·</span>
            <span className="text-foreground/80">Call</span> {callId}
          </div>
        )}

        {mode === "sip" && callId && !session && (
          <div className="flex items-start gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              SIP call dispatched. The agent is dialing. Check Call History for
              transcripts.
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}
