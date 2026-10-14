"use client";

import { getSubscription } from "@/lib/subs";
import { listAgents } from "@/lib/index";
import {
  CreditCard,
  Bot,
  Layers,
  BookOpen,
  Calendar,
  AlertCircle,
  Sparkles,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { LoadingGrid } from "@/components/LoadingGrid";
import { useQuery } from "@tanstack/react-query";

/**
 * CurrentPlanCard — full-width primary solid card showing active entitlements.
 * Self-loads subscription + agent count (same APIs as SubscriptionPanel).
 * Does not include purchase/recharge UI.
 */

export default function MyPlan() {
  const {
    data,
    isPending,
    error
  } = useQuery({
    queryKey: ["subcriptions", "agents"],
    queryFn: async () => {
      const [s, a] = await Promise.all([getSubscription(), listAgents()]);
      return {
        subcriptions: s,
        agents: (a as { agents: unknown[] }).agents?.length || 0,
      };
    },
  });

  const info = data?.subcriptions;
  const agents = data?.agents;

  if (isPending && !info) {
    return (
      <LoadingGrid
        loading={isPending}
        error={error}
        text="Loading your plan..."
      />
    );
  }

  if (!info) {
    return (
      <div className="flex w-full items-center gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm font-medium text-destructive shadow-sm">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-destructive/10">
          <AlertCircle className="h-4 w-4" />
        </div>
        <p className="leading-snug">
          {error?.message || "Plan info unavailable"}
        </p>
      </div>
    );
  }

  const ent = info.entitlement;
  const isActive = ent.status === "active";
  const isPastDue = ent.status === "past_due";

  return (
    <div
      className={cn(
        "relative w-full overflow-hidden rounded-2xl border transition-all duration-500",
        isActive
          ? "border-primary/30 bg-primary shadow-[0_8px_40px_-12px_hsl(var(--primary)/0.5)]"
          : "border-border bg-card shadow-sm",
      )}
    >
      {/* ── Active-state visual layers ── */}
      {isActive && (
        <>
          {/* Top accent gradient stripe */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-primary-foreground/50 to-transparent"
          />

          {/* Soft diagonal light wash */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary-foreground/[0.06] via-transparent to-transparent"
          />

          {/* Dot mesh */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.05]"
            style={{
              backgroundImage:
                "radial-gradient(circle at 1px 1px, currentColor 0.8px, transparent 0)",
              backgroundSize: "24px 24px",
            }}
          />

          {/* Ambient glow — top-right */}
          <div
            aria-hidden
            className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-primary-foreground/15 blur-[80px]"
          />

          {/* Ambient glow — bottom-left */}
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-28 -left-16 h-60 w-60 rounded-full bg-primary-foreground/10 blur-[60px]"
          />
        </>
      )}

      <div className="relative space-y-7 p-6 sm:p-8 lg:p-9">
        {/* ── Header ── */}
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          {/* Left: icon + title + description */}
          <div className="flex items-start gap-4">
            {/* Icon container */}
            <div
              className={cn(
                "relative flex h-13 w-13 shrink-0 items-center justify-center rounded-xl",
                isActive
                  ? "bg-primary-foreground text-primary shadow-lg shadow-primary-foreground/20"
                  : "border border-border bg-muted/50 text-muted-foreground",
              )}
            >
              {isActive ? (
                <ShieldCheck className="h-6 w-6 stroke-[2.2]" />
              ) : (
                <CreditCard className="h-6 w-6 stroke-[1.8]" />
              )}
              {isActive && (
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 rounded-xl bg-primary-foreground/20 blur-md"
                />
              )}
            </div>

            <div className="min-w-0 space-y-1.5">
              <div className="flex flex-wrap items-center gap-2.5">
                <h2
                  className={cn(
                    "text-xl font-bold tracking-tight sm:text-2xl",
                    isActive ? "text-primary-foreground" : "text-foreground",
                  )}
                >
                  {isActive ? "Your current plan" : "No active plan"}
                </h2>

                <Badge
                  className={cn(
                    "h-6 gap-1.5 border px-2.5 text-[11px] font-semibold tracking-wide capitalize shadow-none",
                    isActive &&
                      "border-primary-foreground/20 bg-primary-foreground/15 text-primary-foreground backdrop-blur-md hover:bg-primary-foreground/20",
                    isPastDue &&
                      "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-300",
                    !isActive &&
                      !isPastDue &&
                      "border-border bg-muted text-muted-foreground hover:bg-muted",
                  )}
                >
                  {isActive && (
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    </span>
                  )}
                  {ent.status}
                </Badge>
              </div>

              <p
                className={cn(
                  "max-w-xl text-sm leading-relaxed",
                  isActive
                    ? "text-primary-foreground/75"
                    : "text-muted-foreground",
                )}
              >
                {isActive
                  ? "Workspace allocation for agents, concurrency, knowledge base, and billing cycle."
                  : isPastDue
                    ? "Payment is past due — recharge to restore full workspace capabilities."
                    : "Purchase a monthly plan below to unlock agents and voice calling."}
              </p>
            </div>
          </div>

          {/* Right: pricing glass card */}
          {isActive && (
            <div className="relative flex shrink-0 items-center gap-4 rounded-xl border border-primary-foreground/15 bg-primary-foreground/[0.08] px-5 py-3.5 shadow-inner backdrop-blur-md">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-foreground/15 shadow-sm">
                <Zap className="h-5 w-5 text-primary-foreground" />
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary-foreground/60">
                  Monthly Total
                </span>
                <div className="flex items-baseline gap-1">
                  <span className="text-2xl font-extrabold tracking-tight tabular-nums text-primary-foreground">
                    ₹{ent.monthly_total.toFixed(2)}
                  </span>
                  <span className="text-xs font-medium text-primary-foreground/60">
                    /mo
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Metrics grid / Inactive banner ── */}
        {isActive ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric
              icon={Bot}
              label="Agents"
              value={`${agents} / ${ent.agent_limit}`}
              solid
            />
            <Metric
              icon={Layers}
              label="Concurrent Lines"
              value={String(ent.concurrency_lines)}
              solid
            />
            <Metric
              icon={BookOpen}
              label="KB Allowance"
              value={`${(ent.kb_char_limit / 1000).toFixed(0)}k chars · ${ent.kb_faq_limit} FAQs`}
              solid
            />
            <Metric
              icon={Calendar}
              label="Renews On"
              value={ent.renews_at ? ent.renews_at.slice(0, 10) : "—"}
              solid
            />
          </div>
        ) : (
          <div
            className={cn(
              "flex items-start gap-3.5 rounded-xl border p-4 text-sm",
              isPastDue
                ? "border-amber-500/25 bg-amber-500/[0.07] text-amber-900 dark:text-amber-200"
                : "border-border bg-muted/30 text-muted-foreground",
            )}
          >
            <div
              className={cn(
                "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                isPastDue ? "bg-amber-500/15" : "bg-muted",
              )}
            >
              <AlertCircle className="h-4 w-4" />
            </div>
            <p className="leading-relaxed">
              {isPastDue
                ? "Monthly payment is due. Recharge your wallet to keep calling lines and building agents active."
                : 'No active plan found. Use "Change / extend your plan" below to configure capacity, lines, telephony, and KB packs.'}
            </p>
          </div>
        )}

        {/* ── Footer ── */}
        {isActive && (
          <div className="flex items-center gap-2 border-t border-primary-foreground/10 pt-4 text-xs text-primary-foreground/65">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary-foreground/80" />
            <p className="leading-normal">
              Entitlements apply to this workspace · Scale or modify your plan
              anytime below
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────
   Metric tile — glass-morphic stat card
   ────────────────────────────────────────────── */
function Metric({
  icon: Icon,
  label,
  value,
  solid,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  solid?: boolean;
}) {
  return (
    <div
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-xl border p-4 transition-all duration-200",
        solid
          ? "border-primary-foreground/10 bg-primary-foreground/[0.06] hover:border-primary-foreground/20 hover:bg-primary-foreground/[0.10]"
          : "border-border bg-card hover:bg-muted/40",
      )}
    >
      {/* Subtle inner glow on hover (active only) */}
      {solid && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{
            background:
              "radial-gradient(ellipse at 30% 0%, hsl(var(--primary-foreground) / 0.06), transparent 70%)",
          }}
        />
      )}

      {/* Top row: icon + label */}
      <div className="relative flex items-center gap-2.5">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-transform duration-200 group-hover:scale-110",
            solid
              ? "bg-primary-foreground/15 text-primary-foreground"
              : "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        <span
          className={cn(
            "text-[11px] font-medium uppercase tracking-wider",
            solid ? "text-primary-foreground/65" : "text-muted-foreground",
          )}
        >
          {label}
        </span>
      </div>

      {/* Value — the hero */}
      <p
        className={cn(
          "relative mt-3 text-xl font-extrabold tracking-tight tabular-nums leading-none",
          solid ? "text-primary-foreground" : "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  );
}
