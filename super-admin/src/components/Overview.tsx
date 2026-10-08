"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { motion, type Variants } from "framer-motion";
import {
  Users,
  Brain,
  Key,
  CreditCard,
  ScrollText,
  Wallet,
  TrendingUp,
  PhoneCall,
  Server,
  Database,
  Layers,
  Boxes,
  RefreshCw,
  RotateCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ArrowUpRight,
  Info,
} from "lucide-react";
import PageHeader, { useBusy } from "@/components/PageHeader";
import {
  adminStats,
  adminHealth,
  reloadConfig,
  type Stats,
  type AdminHealth,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { StateBox } from "./StateBox";
import { useQuery } from "@tanstack/react-query";

// snapshot_ts arrives as Unix epoch seconds (float). Format to HH:MM:SS.
function fmtEpoch(ts?: number): string {
  if (!ts || !Number.isFinite(ts)) return "—";
  try {
    return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
  } catch {
    return "—";
  }
}

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
  },
};

/* -------------------------------------------------------------------------- */
/*  Hero metric — primary KPI banner                                          */
/* -------------------------------------------------------------------------- */
function HeroMetric({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card className="relative h-full overflow-hidden border-0 bg-primary py-0 text-primary-foreground shadow-sm">
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.12] [background-image:radial-gradient(circle_at_1px_1px,currentColor_1px,transparent_0)] [background-size:14px_14px]"
      />
      <div className="relative flex h-full flex-col justify-between p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary-foreground/15">
              <Icon className="h-4 w-4" strokeWidth={2.5} />
            </div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-primary-foreground/70">
              {label}
            </p>
          </div>
          <Badge className="h-5 border-0 bg-primary-foreground/15 px-2 text-[10px] font-semibold text-primary-foreground hover:bg-primary-foreground/20">
            <span className="relative mr-1.5 flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
            Live
          </Badge>
        </div>
        <div className="mt-5">
          <p className="text-3xl font-bold tracking-tight tabular-nums sm:text-4xl">
            {value}
          </p>
          {sub && (
            <p className="mt-1.5 text-xs font-medium text-primary-foreground/70">
              {sub}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/*  Standard metric — compact catalog & user KPIs                            */
/* -------------------------------------------------------------------------- */
function MetricCard({
  icon: Icon,
  label,
  value,
  sub,
  highlight = false,
  iconColor,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  highlight?: boolean;
  iconColor?: string;
}) {
  return (
    <Card
      className={`flex h-full flex-col border-border/60 py-0 shadow-sm transition-colors hover:border-foreground/20 ${
        highlight ? "bg-primary/5" : "bg-card"
      }`}
    >
      <div className="flex h-full flex-col p-4">
        {/* Top row: label + icon — fixed height */}
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <div
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
              highlight
                ? "bg-primary/10 text-primary"
                : iconColor
                  ? iconColor
                  : "bg-muted/50 text-muted-foreground"
            }`}
          >
            <Icon className="h-4 w-4" strokeWidth={2} />
          </div>
        </div>

        {/* Value block — pushed to bottom via mt-auto for consistent baseline */}
        <div className="mt-auto pt-4">
          <p className="text-2xl font-bold leading-none tracking-tight tabular-nums text-foreground">
            {value}
          </p>
          {sub ? (
            <p className="mt-1.5 truncate text-[11px] leading-none text-muted-foreground">
              {sub}
            </p>
          ) : (
            <p className="mt-1.5 h-[11px]" />
          )}
        </div>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/*  Status row — compact inline system monitor                                */
/* -------------------------------------------------------------------------- */
function StatusRow({
  icon: Icon,
  label,
  value,
  status,
  detail,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  status: "ok" | "warn" | "down";
  detail?: string;
}) {
  const statusMap = {
    ok: {
      iconBg: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
      dot: "bg-emerald-500",
      pulse: "bg-emerald-500",
      badge:
        "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
      label: "Operational",
    },
    warn: {
      iconBg: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
      dot: "bg-amber-500",
      pulse: "bg-amber-500",
      badge:
        "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400",
      label: "Degraded",
    },
    down: {
      iconBg: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
      dot: "bg-rose-500",
      pulse: "bg-rose-500",
      badge:
        "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-400",
      label: "Offline",
    },
  }[status];

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${statusMap.iconBg}`}
        >
          <Icon className="h-4 w-4" strokeWidth={2} />
        </div>
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <div className="mt-0.5 flex items-baseline gap-1.5">
            <span className="text-sm font-semibold text-foreground">
              {value}
            </span>
            {detail && (
              <span className="text-[11px] text-muted-foreground">
                · {detail}
              </span>
            )}
          </div>
        </div>
      </div>
      <Badge
        variant="outline"
        className={`h-6 shrink-0 gap-1.5 px-2 text-[10px] font-semibold ${statusMap.badge}`}
      >
        <span className="relative flex h-1.5 w-1.5">
          {status === "ok" && (
            <span
              className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${statusMap.pulse}`}
            />
          )}
          <span
            className={`relative inline-flex h-1.5 w-1.5 rounded-full ${statusMap.dot}`}
          />
        </span>
        {statusMap.label}
      </Badge>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Quick action tile                                                         */
/* -------------------------------------------------------------------------- */
function QuickAction({
  href,
  icon: Icon,
  label,
  description,
  color,
}: {
  href: string;
  icon: React.ElementType;
  label: string;
  description: string;
  color: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-lg border border-border/60 bg-background p-3.5 transition-all duration-200 hover:border-foreground/20 hover:bg-muted/30 hover:shadow-sm"
    >
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-transform duration-200 group-hover:scale-105 ${color}`}
      >
        <Icon className="h-4 w-4" strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-1">
          <p className="text-sm font-semibold text-foreground">{label}</p>
          <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-all duration-200 group-hover:opacity-100" />
        </div>
        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
    </Link>
  );
}

export default function OverviewPage() {
  const { busy, msg, err, run } = useBusy();

  const {
    data,
    isPending: loading,
    error,
    refetch: reFetchOverview,
  } = useQuery({
    queryKey: ["overview"],
    queryFn: async () => {
      const [stats, health] = await Promise.all([adminStats(), adminHealth()]);
      return { stats, health };
    },
  });

  const stats = data?.stats ?? null;
  const health = data?.health ?? null;
  const errorMessage = error instanceof Error ? error.message : "";

  const snapshotStatus: "ok" | "warn" | "down" =
    health?.snapshot_source === "db"
      ? "ok"
      : health?.snapshot_source
        ? "warn"
        : "down";
  const backendStatus: "ok" | "down" = health?.ok ? "ok" : "down";

  return (
    <div className="flex flex-col pb-10">
      <PageHeader
        title="Overview"
        subtitle="Platform health and configuration snapshot at a glance"
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => reFetchOverview()}
          disabled={loading}
          className="h-9"
        >
          <RefreshCw
            className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
        <Button
          size="sm"
          className="h-9"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await reloadConfig();
              reFetchOverview();
            }, "Config reloaded ✓")
          }
        >
          <RotateCw
            className={`mr-2 h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`}
          />
          {busy ? "Reloading…" : "Reload config"}
        </Button>
      </PageHeader>

      {(msg || err) && (
        <div
          className={`mb-6 flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm font-medium ${
            msg
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "border-destructive/20 bg-destructive/10 text-destructive"
          }`}
        >
          {msg ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0" />
          )}
          <span>{msg || err}</span>
        </div>
      )}

      <StateBox loading={loading} error={error?.message}>
        <motion.div
          className="space-y-6"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {/* ── Primary KPIs ── */}
          <section>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                Key metrics
              </h2>
              <span className="text-xs text-muted-foreground">
                Real-time financial snapshot
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <motion.div variants={itemVariants} className="sm:col-span-2">
                <HeroMetric
                  icon={Wallet}
                  label="Wallet float"
                  value={`₹${stats?.wallet_balance_total?.toFixed(2) ?? "0.00"}`}
                  sub="Sum of all user balances currently held on the platform"
                />
              </motion.div>
              <motion.div variants={itemVariants}>
                <MetricCard
                  icon={TrendingUp}
                  label="Gross Recharges"
                  value={`₹${stats?.wallet_recharge_total?.toFixed(2) ?? "0.00"}`}
                  sub="All-time top-ups"
                  highlight
                  iconColor="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                />
              </motion.div>
              <motion.div variants={itemVariants}>
                <MetricCard
                  icon={PhoneCall}
                  label="Platform Calls"
                  value={stats?.calls ?? 0}
                  sub="Total processed records"
                  iconColor="bg-blue-500/10 text-blue-600 dark:text-blue-400"
                />
              </motion.div>
            </div>
          </section>

          {/* ── Catalog + Health (equal height) ── */}
          <section className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-5">
            {/* Catalog metrics */}
            <div className="flex flex-col lg:col-span-3">
              <div className="mb-3 flex h-5 items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">
                  Catalog & accounts
                </h2>
              </div>
              <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-3">
                <motion.div variants={itemVariants} className="h-full">
                  <MetricCard
                    icon={Users}
                    label="Users"
                    value={stats?.users ?? 0}
                    sub="Registered accounts"
                    iconColor="bg-violet-500/10 text-violet-600 dark:text-violet-400"
                  />
                </motion.div>
                <motion.div variants={itemVariants} className="h-full">
                  <MetricCard
                    icon={Layers}
                    label="Providers"
                    value={`${stats?.enabled_providers ?? 0} / ${stats?.providers ?? 0}`}
                    sub="Enabled / total"
                    iconColor="bg-amber-500/10 text-amber-600 dark:text-amber-400"
                  />
                </motion.div>
                <motion.div variants={itemVariants} className="h-full">
                  <MetricCard
                    icon={Boxes}
                    label="Models"
                    value={`${stats?.enabled_models ?? 0} / ${stats?.models ?? 0}`}
                    sub="Enabled / total"
                    iconColor="bg-cyan-500/10 text-cyan-600 dark:text-cyan-400"
                  />
                </motion.div>
              </div>
            </div>

            {/* System health */}
            <div className="flex flex-col lg:col-span-2">
              <div className="mb-3 flex h-5 items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">
                  System health
                </h2>
                <span className="text-xs text-muted-foreground">
                  Last ping {fmtEpoch(health?.snapshot_ts)}
                </span>
              </div>
              <Card className="flex flex-1 flex-col justify-center border-border/60 py-0 shadow-sm">
                <div className="flex flex-col justify-center gap-4 p-4">
                  <StatusRow
                    icon={Server}
                    label="Backend API"
                    value={health?.ok ? "Online" : "Offline"}
                    status={backendStatus}
                    detail="FastAPI"
                  />
                  <Separator className="bg-border/50" />
                  <StatusRow
                    icon={Database}
                    label="Config Snapshot"
                    value={
                      health?.snapshot_source === "db"
                        ? "Database"
                        : (health?.snapshot_source ?? "—")
                    }
                    status={snapshotStatus}
                    detail={
                      health?.snapshot_error
                        ? "Error"
                        : `src: ${health?.snapshot_source ?? "unknown"}`
                    }
                  />
                </div>
              </Card>
            </div>
          </section>

          {/* ── Quick actions ── */}
          <section>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                Administration
              </h2>
              <span className="text-xs text-muted-foreground">
                Quick access tools
              </span>
            </div>
            <Card className="overflow-hidden border-border/60 py-0 shadow-sm">
              <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                <QuickAction
                  href="/users"
                  icon={Users}
                  label="Users"
                  description="Manage users & roles"
                  color="bg-violet-500/10 text-violet-600 dark:text-violet-400"
                />
                <QuickAction
                  href="/models"
                  icon={Brain}
                  label="Models"
                  description="Provider model catalog"
                  color="bg-blue-500/10 text-blue-600 dark:text-blue-400"
                />
                <QuickAction
                  href="/api-keys"
                  icon={Key}
                  label="API keys"
                  description="Provision & rotate keys"
                  color="bg-amber-500/10 text-amber-600 dark:text-amber-400"
                />
                <QuickAction
                  href="/billing"
                  icon={CreditCard}
                  label="Billing"
                  description="Pricing & plans"
                  color="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                />
                <QuickAction
                  href="/audit-logs"
                  icon={ScrollText}
                  label="Audit logs"
                  description="System activity trail"
                  color="bg-rose-500/10 text-rose-600 dark:text-rose-400"
                />
              </div>

              <div className="flex items-start gap-2.5 border-t border-border/60 bg-muted/20 px-4 py-3">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Dynamic configuration (providers, models, pricing, API keys)
                  lives in the database and is served via an in-memory snapshot.
                  Changes apply without redeploying. If snapshot source shows{" "}
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-foreground">
                    code
                  </code>
                  , DB is unreachable and platform fell back to static defaults.
                </p>
              </div>
            </Card>
          </section>
        </motion.div>
      </StateBox>
    </div>
  );
}
