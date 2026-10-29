"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSubscription,
  purchaseSubscription,
  type PlanOption,
  type SubscriptionInfo,
} from "@/lib/subs";
import { listAgents } from "@/lib/index";
import {
  CreditCard,
  Loader2,
  BookOpen,
  Phone,
  AlertCircle,
  CheckCircle2,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { LoadingGrid } from "../../../../components/LoadingGrid";

function FieldHelp({ label, help }: { label: string; help: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={`Help: ${label}`}
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="h-3.5 w-3.5" />
      </TooltipTrigger>

      <TooltipContent side="top" align="start" className="max-w-64 text-xs">
        <p>{help}</p>
      </TooltipContent>
    </Tooltip>
  );
}

export default function SubscriptionPanel({
  onChanged,
}: {
  onChanged?: () => void;
}) {
  const [info, setInfo] = useState<SubscriptionInfo | null>(null);
  const [agents, setAgents] = useState(0);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const [tierId, setTierId] = useState("");
  const [totalChannels, setTotalChannels] = useState(1);
  const [telephony, setTelephony] = useState(false);
  const [packIds, setPackIds] = useState<string[]>([]);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([getSubscription(), listAgents()])
      .then(([s, a]) => {
        setInfo(s);
        setTotalChannels((current) =>
          current === 1
            ? Math.max(
                1,
                Number(
                  s.entitlement.plan_channels ||
                    s.entitlement.channels ||
                    s.entitlement.concurrency_lines ||
                    1,
                ),
              )
            : current,
        );
        setAgents((a as { agents: unknown[] }).agents?.length || 0);
        setErr("");
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  if (loading && !info)
    return (
      <LoadingGrid
        loading={loading}
        error={err}
        text="Loading plan options..."
      />
    );

  if (!info)
    return (
      <div className="flex items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-xs font-medium text-destructive">
        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
        {err || "Plan info unavailable"}
      </div>
    );

  const channelPrice =
    info.prices.channel_price_per_month ??
    info.prices.line_price_per_month ??
    0;
  const teleRent = info.prices.telephony_rent_per_month;
  const chosenTier: PlanOption | undefined = info.plans.capacity.find(
    (t) => t.id === tierId,
  );
  const chosenPacks = info.plans.kb_packs.filter((p) => packIds.includes(p.id));
  const monthly =
    (chosenTier?.price_per_month || 0) +
    Math.max(totalChannels - 1, 0) * channelPrice +
    (telephony ? teleRent : 0) +
    chosenPacks.reduce((s, p) => s + p.price_per_month, 0);

  const buy = async () => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await purchaseSubscription({
        capacity_tier_id: tierId,
        channels: Math.max(1, Math.trunc(totalChannels)),
        telephony,
        kb_pack_ids: packIds,
      });
      setMsg("Plan activated ✅ — you can build agents and call now.");
      setTierId("");
      setTelephony(false);
      setPackIds([]);
      load();
      onChanged?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <TooltipProvider>
      <section className="w-full min-w-0 space-y-4 overflow-hidden rounded-2xl border border-border bg-card p-4 shadow-sm sm:p-5">
        <header className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <CreditCard className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h2 className="break-words text-base font-semibold leading-tight tracking-tight text-foreground sm:text-lg">
              Choose a plan and add-ons
            </h2>
            <p className="mt-1 break-words text-xs leading-relaxed text-muted-foreground">
              Set your agent capacity, VoiceLink channels, and optional services.
            </p>
          </div>
        </header>

        <div className="rounded-xl border border-border bg-muted/30 p-3 sm:p-4">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-foreground">
              Agent plan and VoiceLink channels
            </h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Choose a base plan and the total simultaneous-call channels
              to use when purchasing and assigning a phone number.
            </p>
          </div>

          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            <div className="min-w-0 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label className="text-xs font-medium text-muted-foreground">
                  Agent plan
                </Label>
                <FieldHelp
                  label="Agent plan"
                  help="Choose the monthly base plan for the number of agents your workspace needs. The plan price and agent allowance are shown in the list."
                />
              </div>

              <Select
                value={tierId || "__none__"}
                onValueChange={(val) =>
                  setTierId(!val || val === "__none__" ? "" : val)
                }
              >
                <SelectTrigger className="h-9 min-w-0 bg-background">
                  <SelectValue placeholder="Choose a plan" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">No plan selected</SelectItem>
                  {info.plans.capacity.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.label} — ₹{t.price_per_month}/mo
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {info.plans.capacity.length === 0 && (
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  Ask the admin to add agent plans (Super Admin → Plans).
                </p>
              )}
            </div>

            <div className="min-w-0 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label
                  htmlFor="voicelink-channels"
                  className="text-xs font-medium text-muted-foreground"
                >
                  VoiceLink channels (total)
                </Label>
                <FieldHelp
                  label="VoiceLink channels"
                  help={`One channel carries one simultaneous phone call. The first channel is included; each additional channel costs ₹${channelPrice}/month. This total becomes the default channel count when you buy a number after KYC.`}
                />
              </div>

              <Input
                id="voicelink-channels"
                type="number"
                min={1}
                max={1000}
                value={totalChannels}
                onChange={(e) => setTotalChannels(Number(e.target.value))}
                className="h-9 bg-background tabular-nums"
              />
              <p className="text-[10px] leading-relaxed text-muted-foreground">
                {Math.max(totalChannels - 1, 0)} additional × ₹
                {channelPrice}/month. Calls on an assigned number are
                capped by that number&apos;s purchased channels.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Optional services
            </h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Select any services or knowledge-base packs to add to this plan.
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <label
              className={cn(
                "flex min-w-0 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 transition-colors",
                telephony
                  ? "border-primary/30 bg-primary/10 text-foreground"
                  : "border-border bg-muted/20 text-muted-foreground hover:bg-muted/40",
              )}
            >
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 accent-primary"
                checked={telephony}
                onChange={(e) => setTelephony(e.target.checked)}
              />
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Phone className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1 text-xs font-medium">
                <span className="block truncate text-foreground">
                  Phone service rental
                </span>
                <span className="mt-0.5 block text-[11px] text-muted-foreground">
                  ₹{teleRent}/month
                </span>
              </span>
              <FieldHelp
                label="Phone service rental"
                help="Monthly rent for the phone number or telephony access used for calling. This is separate from the cost of each call."
              />
            </label>

            {info.plans.kb_packs.map((p) => {
              const on = packIds.includes(p.id);

              return (
                <label
                  key={p.id}
                  className={cn(
                    "flex min-w-0 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 transition-colors",
                    on
                      ? "border-primary/30 bg-primary/10 text-foreground"
                      : "border-border bg-muted/20 text-muted-foreground hover:bg-muted/40",
                  )}
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 shrink-0 accent-primary"
                    checked={on}
                    onChange={(e) =>
                      setPackIds(
                        e.target.checked
                          ? [...packIds, p.id]
                          : packIds.filter((x) => x !== p.id),
                      )
                    }
                  />
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <BookOpen className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1 text-xs font-medium">
                    <span className="block truncate text-foreground">
                      Knowledge base: {p.label}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-muted-foreground">
                      ₹{p.price_per_month}/month
                    </span>
                  </span>
                  <FieldHelp
                    label={`Knowledge base pack ${p.label}`}
                    help="Adds the knowledge-base pack configured by your administrator. Its monthly price is shown here; its allowance is reflected in your plan after activation."
                  />
                </label>
              );
            })}
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-xl border border-border bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Estimated monthly total
              </p>
              <FieldHelp
                label="Estimated monthly total"
                help="The monthly price for the plan and optional services selected above. The first month is charged from your wallet when you activate the plan."
              />
            </div>
            <p className="mt-0.5 text-xl font-bold tabular-nums tracking-tight text-foreground">
              ₹{monthly.toFixed(2)}
              <span className="ml-1 text-xs font-medium text-muted-foreground">
                /month
              </span>
            </p>
          </div>

          <Button
            type="button"
            onClick={buy}
            disabled={busy || monthly <= 0}
            className="h-9 w-full shrink-0 gap-2 sm:w-auto"
          >
            {busy ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Activating…
              </>
            ) : (
              <>
                <CreditCard className="h-3.5 w-3.5" />
                Buy &amp; activate (wallet)
              </>
            )}
          </Button>
        </div>

        <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-[10px] leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-3 w-3 shrink-0" />
          <p>
            The first month is charged from your wallet now; renewals run
            monthly. Recharge below if balance is short.
          </p>
        </div>

        {err && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {err}
          </div>
        )}

        {msg && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {msg}
          </div>
        )}
      </section>
    </TooltipProvider>
  );
}
