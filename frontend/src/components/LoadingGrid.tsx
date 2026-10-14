"use client";

import type { CSSProperties } from "react";
import { AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/card";

type LoadingGridProps = {
  loading: boolean;
  error?: string | null;
  text?: string;
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
};

export function LoadingGrid({
  loading,
  error,
  text = "Loading...",
  width = "100%",
  height = 400,
}: LoadingGridProps) {
  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="loading-shimmer relative flex min-w-0 items-center justify-center overflow-hidden rounded-xl border border-border/50 bg-background"
        style={{ width, height }}
      >
        <style>{`
          @keyframes loadingShimmer {
            to {
              transform: translateX(100%);
            }
          }

          .loading-shimmer::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            transform: translateX(-100%);
            background: linear-gradient(
                100deg,
                transparent 15%,
                rgba(99, 102, 241, 0.10) 35%,
                rgba(99, 102, 241, 0.28) 50%,
                rgba(99, 102, 241, 0.10) 65%,
                transparent 85%
              );
            animation: loadingShimmer 1.8s ease-in-out infinite;
          }

          @media (prefers-reduced-motion: reduce) {
            .loading-shimmer::after {
              animation: none;
              transform: none;
              background: hsl(var(--muted-foreground) / 0.04);
            }
          }

          .dark .loading-shimmer::after {
  background: linear-gradient(
    100deg,
    transparent 15%,
    rgba(165, 180, 252, 0.10) 35%,
    rgba(165, 180, 252, 0.28) 50%,
    rgba(165, 180, 252, 0.10) 65%,
    transparent 85%
  );
}
        `}</style>

        <span className="relative z-10 text-xs font-medium text-muted-foreground">
          {text}
        </span>
        <span className="sr-only">{text}</span>
      </div>
    );
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

  return null;
}
