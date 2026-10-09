"use client";

import { useQuery } from "@tanstack/react-query";
import { getWallet } from "@/lib/index";
import { RefreshCw } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";

export default function DashboardHeader() {
  const {
    data: wallet,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
  });

  const balance = wallet?.balance;

  return (
    <header className="sticky top-0 z-50 flex h-14 shrink-0 items-center justify-between border-b border-border/60 bg-background/95 px-4 backdrop-blur-md lg:px-6">
      <div className="flex items-center gap-2">
        {/* <SidebarTrigger className="-ml-2 text-muted-foreground hover:text-foreground" /> */}
        <Separator
          orientation="vertical"
          className="mr-2 hidden h-4 md:block"
        />
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-muted/30 px-3 py-1.5 shadow-sm">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Balance
          </span>
          <span className="text-sm font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
            {isLoading && balance == null
              ? "—"
              : `₹${(balance ?? 0).toFixed(2)}`}
          </span>
        </div>

        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-8 w-8 shrink-0 border-border/60"
          onClick={() => refetch()}
          disabled={isFetching}
          title="Refresh balance"
          aria-label="Refresh wallet balance"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
          />
        </Button>
      </div>
    </header>
  );
}
