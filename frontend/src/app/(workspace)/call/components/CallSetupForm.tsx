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
          : callState === "ending"
            ? "Ending call…"
            : isCallActive
              ? "Call connected"
            : mode === "browser"
              ? "Start voice call"
              : "Dial number";

  const startPending =
    busy ||
    callState === "connecting" ||
    callState === "waiting_for_agent" ||
    callState === "ending" ||
    (!agentsReady && callState === "idle");
  const inboundOnly =
    selected != null &&
    !["outbound", "both"].includes(selected.purpose || "outbound");
  const hasAssignedNumber = Boolean(selected?.phone_number_id);

  return (
    <Card className="overflow-hidden border-border/70 bg-card py-0 shadow-sm">
      <div className="flex flex-col gap-5 p-5 sm:p-6">
        {/* Agent */}
        <div className="space-y-2">
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
                "flex h-11 w-full appearance-none rounded-lg border border-input bg-background py-1 pl-9 pr-8 text-sm shadow-sm transition-colors",
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
            <div className="flex items-start gap-2.5 rounded-lg border border-primary/10 bg-primary/[0.04] px-3 py-2.5">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {selected.agent_mode === "announcement"
                  ? selected.end_after_announcement
                    ? "Announcement mode: plays a fixed script, then ends the call automatically."
                    : "Announcement mode: plays a fixed script and stays open until you end the call."
                  : "Assistant mode: greets on connect, then listens and converses turn by turn."}
                {` Purpose: ${selected.purpose || "outbound"}.`}
                {selected.phone_number
                  ? ` Assigned caller number: ${selected.phone_number}.`
                  : " No assigned phone number."}
              </p>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
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
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              disabled={isCallActive}
              onClick={() => onModeChange("browser")}
              className={cn(
                "inline-flex h-11 items-center justify-center gap-2 rounded-lg border text-xs font-semibold transition-all disabled:opacity-50",
                mode === "browser"
                  ? "border-primary/30 bg-primary/5 text-primary shadow-sm"
                  : "border-border bg-background text-muted-foreground hover:bg-muted/40 hover:text-foreground",
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
              disabled={isCallActive || inboundOnly}
              onClick={() => onModeChange("sip")}
              className={cn(
                "inline-flex h-11 items-center justify-center gap-2 rounded-lg border text-xs font-semibold transition-all disabled:opacity-50",
                mode === "sip"
                  ? "border-primary/30 bg-primary/5 text-primary shadow-sm"
                  : "border-border bg-background text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
            >
              <Phone className="h-3.5 w-3.5" />
              SIP phone
            </button>
          </div>
        </div>

        {mode === "sip" && inboundOnly && (
          <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-800 dark:text-amber-300">
            This agent is inbound-only. Switch to Browser testing or choose an
            outbound/both-purpose agent.
          </div>
        )}

        {/* SIP fields */}
        {mode === "sip" && (
          <div className="space-y-3 rounded-xl border border-border/70 bg-muted/20 p-3.5">
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
            {hasAssignedNumber ? (
              <div className="rounded-lg border border-primary/15 bg-primary/5 px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
                Calling from assigned number{" "}
                <span className="font-mono font-semibold text-foreground">
                  {selected?.phone_number || "purchased number"}
                </span>
                . Its SIP trunk and caller ID are managed automatically by the
                backend.
              </div>
            ) : (
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
            )}
            <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <Info className="mt-0.5 h-3 w-3 shrink-0" />
              Requires a LiveKit SIP trunk and carrier credentials on the
              backend.
            </p>
          </div>
        )}

        {/* Error */}
        {err && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2.5 text-sm font-medium text-destructive">
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
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="leading-snug">{callEndedMsg}</span>
          </div>
        )}

        {/* Primary actions */}
        <div className="space-y-2 border-t border-border/60 pt-4">
          <Button
            type="button"
            className="h-11 w-full gap-2 text-sm font-semibold shadow-sm"
            onClick={onStart}
            disabled={
              busy ||
              isCallActive ||
              !agentId ||
              !agentsReady ||
              (mode === "sip" && inboundOnly)
            }
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
              className="h-11 w-full gap-2 text-sm font-semibold shadow-sm"
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
          <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 font-mono text-[11px] text-muted-foreground">
            <span className="text-foreground/80">Room</span> {session.room}
            <span className="mx-1.5 text-border">·</span>
            <span className="text-foreground/80">Call</span> {callId}
          </div>
        )}

        {mode === "sip" && callId && !session && isCallActive && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              {callState === "ending"
                ? "Ending the SIP call…"
                : "SIP call in progress. Hang up on the phone or use End call here; this page will update automatically when it finishes."}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}
