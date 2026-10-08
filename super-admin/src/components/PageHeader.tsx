"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Inbox, Terminal } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/* -------------------------------------------------------------------------- */
/*  Digital Dot-Matrix Grid Loader                                            */
/* -------------------------------------------------------------------------- */
function DotMatrixLoader() {
  const rows = 4;
  const cols = 7;

  return (
    <div className="flex flex-col items-center justify-center">
      {/* Ambient background glow */}
      <div className="relative flex items-center justify-center p-6">
        <div className="absolute -inset-2 rounded-full bg-primary/10 blur-xl animate-pulse" />

        {/* Matrix Grid */}
        <div className="relative grid grid-cols-7 gap-2">
          {Array.from({ length: rows * cols }).map((_, i) => {
            const row = Math.floor(i / cols);
            const col = i % cols;
            // Calculate delay based on distance from center for a ripple wave effect
            const distFromCenter = Math.sqrt(
              Math.pow(col - (cols - 1) / 2, 2) +
                Math.pow(row - (rows - 1) / 2, 2),
            );

            return (
              <motion.div
                key={i}
                initial={{ opacity: 0.15, scale: 0.8 }}
                animate={{
                  opacity: [0.15, 0.9, 0.15],
                  scale: [0.8, 1.25, 0.8],
                  backgroundColor: [
                    "hsl(var(--muted-foreground) / 0.2)",
                    "hsl(var(--primary))",
                    "hsl(var(--muted-foreground) / 0.2)",
                  ],
                }}
                transition={{
                  duration: 1.8,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: distFromCenter * 0.14,
                }}
                className="h-2 w-2 rounded-[2px]"
              />
            );
          })}
        </div>
      </div>

      <div className="mt-2 flex flex-col items-center gap-1.5 text-center">
        <div className="flex items-center gap-2">
          <span className="flex h-1.5 w-1.5 rounded-full bg-primary animate-ping" />
          <p className="text-xs font-semibold tracking-wider uppercase text-foreground">
            Synchronizing
          </p>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Fetching live data stream…
        </p>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Page Header Component                                                     */
/* -------------------------------------------------------------------------- */
export default function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-1">
        <h1 className="truncate text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
          {title}
        </h1>
        {subtitle && (
          <p className="max-w-2xl text-sm leading-normal text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      {children && (
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {children}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Universal State Handler                                                   */
/* -------------------------------------------------------------------------- */
export function StateBox({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: string | null;
  children: React.ReactNode;
}) {
  if (loading) {
    return (
      <Card className="relative flex min-h-[300px] w-full flex-col items-center justify-center overflow-hidden border-border/60 bg-card/60 p-8 shadow-sm backdrop-blur-sm">
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.03] [background-image:radial-gradient(circle_at_1px_1px,currentColor_1px,transparent_0)] [background-size:16px_16px]"
        />
        <DotMatrixLoader />
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="overflow-hidden border-rose-500/20 bg-rose-500/5 shadow-sm">
        <div className="flex items-start gap-3.5 p-5">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-rose-500/20 bg-rose-500/10">
            <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-400" />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-rose-700 dark:text-rose-400">
                Data Stream Error
              </p>
              <Badge
                variant="outline"
                className="h-4 px-1 text-[9px] font-mono border-rose-500/30 text-rose-600 dark:text-rose-400"
              >
                500
              </Badge>
            </div>
            <p className="text-[13px] leading-relaxed text-rose-700/80 dark:text-rose-400/80 font-mono">
              {error}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  if (empty) {
    return (
      <Card className="relative flex min-h-[260px] flex-col items-center justify-center overflow-hidden border-border/60 bg-card/40 px-6 py-12 text-center shadow-sm">
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.03] [background-image:radial-gradient(circle_at_1px_1px,currentColor_1px,transparent_0)] [background-size:16px_16px]"
        />
        <div className="relative flex h-12 w-12 items-center justify-center rounded-xl border border-border/60 bg-muted/40 shadow-inner">
          <Inbox className="h-5 w-5 text-muted-foreground" />
        </div>
        <p className="relative mt-4 text-sm font-semibold text-foreground">
          No records found
        </p>
        <p className="relative mt-1 max-w-sm text-[12px] leading-relaxed text-muted-foreground">
          {empty}
        </p>
      </Card>
    );
  }

  return <>{children}</>;
}

/* -------------------------------------------------------------------------- */
/*  Busy State Logic Hook                                                     */
/* -------------------------------------------------------------------------- */
export function useBusy() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const run = async <T,>(fn: () => Promise<T>, okMsg = "Saved ✓") => {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      const out = await fn();
      setMsg(okMsg);
      setTimeout(() => setMsg(""), 3000);
      return out;
    } catch (e) {
      setErr((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, err, run, setErr, setMsg };
}
