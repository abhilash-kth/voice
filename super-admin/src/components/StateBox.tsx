"use client";

import { useMemo } from "react";
import { AlertCircle, Inbox } from "lucide-react";
import { Card } from "@/components/ui/card";

function FullPageDotMatrix() {
  const rows = 20;
  const cols = 50;

  const dots = useMemo(() => {
    const list: { id: string; delay: number; opacity: number }[] = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        list.push({
          id: `${r}-${c}`,
          delay: Math.random() * 2500,
          opacity: Number((0.06 + Math.random() * 0.18).toFixed(2)), // Subtle, faded primary dots
        });
      }
    }
    return list;
  }, []);

  return (
    <div className="relative flex min-h-[520px] w-full flex-col items-center justify-center overflow-hidden">
      <style>{`
        @keyframes subtleDotBlink {
          0%, 100% { opacity: var(--base-opacity); transform: scale(1); }
          50% { opacity: calc(var(--base-opacity) * 2.5); transform: scale(1.2); }
        }
      `}</style>

      {/* Full-bleed primary dot grid spreading edge-to-edge */}
      <div
        className="absolute inset-0 grid h-full w-full items-center justify-items-center p-4"
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        }}
      >
        {dots.map((dot) => (
          <div
            key={dot.id}
            className="h-1 w-1 rounded-full bg-primary"
            style={
              {
                "--base-opacity": dot.opacity,
                opacity: dot.opacity,
                animation: `subtleDotBlink 2.2s infinite ease-in-out`,
                animationDelay: `${dot.delay}ms`,
                willChange: "opacity, transform",
              } as React.CSSProperties
            }
          />
        ))}
      </div>

      {/* Floating status caption */}
      <div className="relative z-10 bg-background/80 px-4 py-2.5">
        <p className="text-xs font-medium tracking-wide text-primary">
          Loading...
        </p>
      </div>
    </div>
  );
}

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
    return <FullPageDotMatrix />;
  }

  if (error) {
    return (
      <Card className="border-destructive/30 bg-destructive/5 p-5 shadow-xs">
        <div className="flex items-start gap-3.5">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-destructive/20 bg-destructive/10 text-destructive">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-semibold text-foreground">
              Failed to load data
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {error}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  if (empty) {
    return (
      <Card className="flex min-h-[280px] w-full flex-col items-center justify-center p-8 text-center shadow-xs">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-muted/40 text-muted-foreground">
          <Inbox className="h-6 w-6" strokeWidth={1.75} />
        </div>
        <p className="mt-4 text-sm font-semibold text-foreground">
          No records found
        </p>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
          {empty}
        </p>
      </Card>
    );
  }

  return <>{children}</>;
}
