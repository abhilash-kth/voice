"use client";

import Link from "next/link";
import { MessageSquare, Megaphone, Trash2, FileText, Plus } from "lucide-react";
import CostEstimate from "./CostEstimate";
import { Toggle } from "./ProviderOptions";
import { GENDER_VOICE_HINT, LANGUAGES } from "./constants";
import type { LeftState, LeftSetters } from "./columnTypes";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type { LeftState, LeftSetters } from "./columnTypes";

export default function LeftColumn({
  v,
  set,
}: {
  v: LeftState;
  set: LeftSetters;
}) {
  const selectedPhone = v.phoneNumbers.find((n) => n.id === v.phoneNumberId);

  return (
    <div className="space-y-8">
      {/* ── SECTION 1: Identity & Mode ── */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-foreground">
          Identity & Behavior
        </h3>

        <div className="rounded-2xl bg-muted/20 p-5 sm:p-6">
          <div className="mb-6 grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Agent Name</Label>
              <Input
                value={v.name}
                onChange={(e) => set.setName(e.target.value)}
                placeholder="e.g. Kavya"
                className="bg-background"
              />
            </div>

            <div className="space-y-2">
              <Label>Agent Mode</Label>
              <div className="grid grid-cols-2 gap-1 rounded-md bg-muted/40 p-1">
                <button
                  type="button"
                  onClick={() => set.setMode("assistant")}
                  className={cn(
                    "flex h-9 items-center justify-center gap-2 rounded-sm text-xs font-semibold transition-all",
                    v.mode === "assistant"
                      ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  Assistant
                </button>
                <button
                  type="button"
                  onClick={() => set.setMode("announcement")}
                  className={cn(
                    "flex h-9 items-center justify-center gap-2 rounded-sm text-xs font-semibold transition-all",
                    v.mode === "announcement"
                      ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Megaphone className="h-3.5 w-3.5" />
                  Announcement
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <Label>
                Call purpose <span className="text-destructive">*</span>
              </Label>
              <div className="grid grid-cols-3 gap-1 rounded-md bg-muted/40 p-1">
                {(
                  [
                    ["outbound", "Outbound"],
                    ["inbound", "Inbound"],
                    ["both", "Both"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => set.setPurpose(value)}
                    className={cn(
                      "flex h-9 items-center justify-center rounded-sm text-xs font-semibold transition-all",
                      v.purpose === value
                        ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {v.purpose === "inbound"
                  ? "Receives calls on its assigned number. Cannot place calls or run campaigns."
                  : v.purpose === "both"
                    ? "Places calls/campaigns and receives calls on its assigned number."
                    : v.purpose === "outbound"
                      ? "Places phone calls and runs campaigns. Does not receive inbound calls."
                      : "Required — choose what this agent is for."}
              </p>
            </div>

            <div className="space-y-2">
              <Label>Assigned phone number (optional)</Label>
              <select
                value={v.phoneNumberId}
                onChange={(e) => set.setPhoneNumberId(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <option value="">No number (browser / default trunk)</option>
                {v.phoneNumbers.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.number} · {n.channels} channel{n.channels === 1 ? "" : "s"}
                    {n.status !== "active" ? ` (${n.status})` : ""}
                  </option>
                ))}
              </select>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {v.phoneNumbers.length === 0 ? (
                  <>
                    No active numbers yet. Buy one on the{" "}
                    <Link className="text-primary underline" href="/phone-numbers">
                      Phone Numbers
                    </Link>{" "}
                    page.
                  </>
                ) : selectedPhone ? (
                  `Outbound calls use this number as caller ID. It has ${selectedPhone.channels} purchased channel${selectedPhone.channels === 1 ? "" : "s"} for simultaneous SIP calls.`
                ) : (
                  "Outbound calls use this number as caller ID; inbound calls to it reach this agent when purpose allows."
                )}
              </p>
            </div>

            {v.mode !== "announcement" && (
              <>
                <div className="space-y-2">
                  <Label>Greeting</Label>
                  <Textarea
                    value={v.greeting}
                    onChange={(e) => set.setGreeting(e.target.value)}
                    rows={2}
                    placeholder="Namaste! Main Kavya hoon..."
                    className="min-h-[72px] resize-y bg-background"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Fallback Response</Label>
                  <Textarea
                    value={v.fallbackResponse}
                    onChange={(e) => set.setFallbackResponse(e.target.value)}
                    rows={2}
                    placeholder="Please hold on, I am having a temporary issue."
                    className="min-h-[72px] resize-y bg-background"
                  />
                </div>
                <div className="space-y-2">
                  <Label>No-response timeout (sec)</Label>
                  <Input
                    type="number"
                    min={15}
                    value={v.noResponseTimeout}
                    onChange={(e) =>
                      set.setNoResponseTimeout(Number(e.target.value))
                    }
                    className="bg-background tabular-nums"
                  />
                </div>
                <div className="space-y-2">
                  <Label>No-response closing message</Label>
                  <Textarea
                    value={v.noResponseMessage}
                    onChange={(e) => set.setNoResponseMessage(e.target.value)}
                    rows={2}
                    className="min-h-[72px] resize-y bg-background"
                  />
                </div>
              </>
            )}

            {v.mode === "announcement" && (
              <div className="space-y-4 md:col-span-2">
                <div className="space-y-2">
                  <Label>Fixed script (announcement)</Label>
                  <Textarea
                    value={v.announceText}
                    onChange={(e) => set.setAnnounceText(e.target.value)}
                    rows={3}
                    placeholder="Namaste! Ye ek reminder hai..."
                    className="min-h-[88px] resize-y border-blue-500/30 bg-blue-500/5 focus-visible:ring-blue-500/40"
                  />
                </div>
                <Toggle
                  on={v.endAfterAnnouncement}
                  set={set.setEndAfterAnnouncement}
                  label="End call after announcement"
                  hint="Automatically hang up when script finishes"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── SECTION 2: Voice & Capacity ── */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-foreground">
          Voice & Capacity
        </h3>

        <div className="rounded-2xl bg-muted/20 p-5 sm:p-6">
          <div className="grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Personality</Label>
              <Select
                value={v.personality}
                onValueChange={(val) => val && set.setPersonality(val)}
              >
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="Select personality" />
                </SelectTrigger>
                <SelectContent>
                  {[
                    "friendly",
                    "professional",
                    "cautious",
                    "playful",
                    "formal",
                  ].map((p) => (
                    <SelectItem key={p} value={p}>
                      <span className="capitalize">{p}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Max concurrent calls</Label>
              <Input
                type="number"
                min={1}
                value={v.maxConcurrency}
                onChange={(e) => set.setMaxConcurrency(Number(e.target.value))}
                className="bg-background tabular-nums"
              />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {selectedPhone
                  ? `SIP calls on ${selectedPhone.number} are capped by its ${selectedPhone.channels} channel${selectedPhone.channels === 1 ? "" : "s"}.`
                  : "Assign a phone number above to use its purchased VoiceLink channels for SIP concurrency."}
              </p>
              <div className="pt-1">
                <CostEstimate
                  mode={v.mode}
                  llmId={v.picked.llm}
                  sttId={v.picked.stt}
                  ttsId={v.picked.tts}
                  teleId={v.picked.telephony}
                  maxConcurrency={v.maxConcurrency}
                />
              </div>
            </div>

            {v.mode !== "announcement" && (
              <>
                <div className="space-y-2">
                  <Label>Language</Label>
                  <Select
                    value={v.language}
                    onValueChange={(val) => val && set.setLanguage(val)}
                  >
                    <SelectTrigger className="bg-background">
                      <SelectValue placeholder="Select language" />
                    </SelectTrigger>
                    <SelectContent>
                      {LANGUAGES.map((l) => (
                        <SelectItem key={l.id} value={l.id}>
                          {l.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Voice gender</Label>
                  <Select
                    value={v.gender}
                    onValueChange={(val) => val && set.setGender(val)}
                  >
                    <SelectTrigger className="bg-background">
                      <SelectValue placeholder="Select gender" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="female">Female</SelectItem>
                      <SelectItem value="male">Male</SelectItem>
                      <SelectItem value="neutral">Neutral</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-[11px] text-muted-foreground">
                    {GENDER_VOICE_HINT[v.gender] || GENDER_VOICE_HINT.female}
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── SECTION 3: Knowledge Base ── */}
      {v.mode === "assistant" && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground">
            Knowledge Base & System
          </h3>

          <div className="rounded-2xl bg-muted/20 p-5 sm:p-6">
            <div className="mb-6 grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
              <div className="space-y-2">
                <Toggle
                  on={v.memoryEnabled}
                  set={set.setMemoryEnabled}
                  label="Conversation memory"
                  hint="Agent remembers this customer across calls"
                />
              </div>
              <div className="space-y-2">
                <Toggle
                  on={v.recordingEnabled}
                  set={set.setRecordingEnabled}
                  label="Call recording"
                  hint="Record the audio via LiveKit Egress"
                />
              </div>

              <div className="space-y-2 md:col-span-2">
                <Label>System prompt (optional)</Label>
                <Textarea
                  value={v.systemPrompt}
                  onChange={(e) => set.setSystemPrompt(e.target.value)}
                  rows={3}
                  placeholder="Extra instructions for the agent..."
                  className="min-h-[88px] resize-y bg-background"
                />
              </div>

              <div className="space-y-2 md:col-span-2">
                <Label>Knowledge base (pasted text / notes)</Label>
                <Textarea
                  value={v.knowledgeText}
                  disabled={!!v.file || v.savedDocuments.length > 0}
                  onChange={(e) => set.setKnowledgeText(e.target.value)}
                  rows={4}
                  placeholder="Company facts, FAQs, product info..."
                  className="min-h-[120px] resize-y bg-background disabled:opacity-50"
                />
              </div>
            </div>

            {/* FAQ */}
            <div className="mb-6 rounded-xl border border-border/60 bg-background p-4 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Label>Frequently Asked Questions</Label>
                  <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                    {v.faq.length} pairs
                  </Badge>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs"
                  onClick={() => set.setFaq((f) => [...f, { q: "", a: "" }])}
                >
                  <Plus className="h-3 w-3" />
                  Add QA
                </Button>
              </div>

              <div className="space-y-3">
                {v.faq.map((item, i) => (
                  <div
                    key={i}
                    className="flex flex-col gap-2 rounded-lg bg-muted/40 p-3 sm:flex-row sm:items-start"
                  >
                    <Input
                      value={item.q}
                      onChange={(e) =>
                        set.setFaq((f) =>
                          f.map((x, j) =>
                            j === i ? { ...x, q: e.target.value } : x,
                          ),
                        )
                      }
                      placeholder="Question"
                      className="bg-background text-sm"
                    />
                    <Input
                      value={item.a}
                      onChange={(e) =>
                        set.setFaq((f) =>
                          f.map((x, j) =>
                            j === i ? { ...x, a: e.target.value } : x,
                          ),
                        )
                      }
                      placeholder="Answer"
                      className="bg-background text-sm"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      onClick={() =>
                        set.setFaq((f) => f.filter((_, j) => j !== i))
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {/* File Upload */}
            <div className="space-y-2">
              <Label>Upload knowledge file (.txt / .pdf / .csv)</Label>
              {v.savedDocuments.length > 0 && (
                <div className="mb-3 rounded-lg border border-blue-500/20 bg-blue-500/10 p-3 text-sm">
                  <div className="mb-2 flex items-center gap-1.5 font-semibold text-blue-700 dark:text-blue-400">
                    <FileText className="h-4 w-4" />
                    Saved File
                  </div>
                  {v.savedDocuments.map((d, i) => (
                    <div
                      key={`${d.name}-${i}`}
                      className="flex items-center justify-between"
                    >
                      <span className="font-mono text-xs">{d.name}</span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                        onClick={() =>
                          set.setSavedDocuments((docs) =>
                            docs.filter((_, j) => j !== i),
                          )
                        }
                      >
                        Delete
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              <Input
                type="file"
                disabled={v.hasText}
                onChange={(e) => set.setFile(e.target.files?.[0] || null)}
                className="h-10 cursor-pointer bg-background file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-sm file:font-medium disabled:opacity-50"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
