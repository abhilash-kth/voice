"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Loader2, Plus } from "lucide-react";
import { recharge } from "@/lib/index";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const PRESET_AMOUNTS = [100, 250, 500, 1000] as const;

export default function AddFundsCard() {
  const queryClient = useQueryClient();
  const [customAmt, setCustomAmt] = useState("");
  const [pendingAmount, setPendingAmount] = useState<number | null>(null);

  const addFunds = useMutation({
    mutationFn: async (amt: number) => {
      if (!amt || amt <= 0) throw new Error("Please enter a valid amount.");
      return await recharge(amt);
    },
    onSuccess: (_, amt) => {
      toast.success(`Recharge ₹${amt} successful`);
      queryClient.invalidateQueries({
        queryKey: ["usage", "wallet-balance"],
      });
      setCustomAmt("");
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const customValue = Math.floor(Number(customAmt));
  const customValid = customValue > 0;
  const isPending = addFunds.isPending;

  const confirmRecharge = () => {
    if (pendingAmount === null || isPending) return;

    const amount = pendingAmount;
    setPendingAmount(null);
    addFunds.mutate(amount);
  };

  return (
    <section
      aria-labelledby="add-funds-title"
      className="w-full min-w-0 overflow-hidden rounded-2xl bg-orange-100 p-4 shadow-sm sm:p-5"
    >
      <header className="mb-4 flex min-w-0 items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-400 text-primary-foreground shadow-sm">
          <Plus className="h-4 w-4" />
        </div>

        <div className="min-w-0">
          <h2
            id="add-funds-title"
            className="break-words text-base font-semibold leading-tight tracking-tight text-foreground sm:text-lg"
          >
            Add funds
          </h2>
          <p className="mt-1 break-words text-xs leading-relaxed text-muted-foreground">
            Choose an amount, then confirm your top-up.
          </p>
        </div>
      </header>

      <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)]">
        <div className="min-w-0 rounded-md bg-white/60 p-3">
          <p className="mb-2.5 text-xs font-semibold text-foreground">
            Choose an amount
          </p>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {PRESET_AMOUNTS.map((amount) => {
              const label =
                amount >= 500
                  ? "Popular"
                  : amount >= 250
                    ? "Standard"
                    : "Quick top-up";
              const isSelected = customValue === amount;

              return (
                <button
                  key={amount}
                  type="button"
                  disabled={isPending}
                  aria-pressed={isSelected}
                  aria-label={`Select ₹${amount} ${label}`}
                  onClick={() => setCustomAmt(String(amount))}
                  className={cn(
                    "flex min-w-0 flex-col items-start justify-center rounded-lg border px-2.5 py-2 text-left transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    isSelected
                      ? "bg-orange-100 ring ring-orange-300"
                      : "border-border bg-background hover:border-primary/40 hover:bg-card",
                  )}
                >
                  <span className="flex w-full items-center justify-between gap-1">
                    <span className="truncate text-sm font-semibold tabular-nums text-foreground">
                      ₹{amount.toLocaleString("en-IN")}
                    </span>
                    {isSelected && (
                      <Check
                        className="h-3.5 w-3.5 shrink-0 text-primary"
                        aria-hidden="true"
                      />
                    )}
                  </span>

                  <span
                    className={cn(
                      "mt-1 max-w-full truncate rounded-full px-1.5 py-0.5 text-[9px] font-medium leading-none",
                      label === "Popular" &&
                        "bg-amber-500/15 text-amber-800 dark:text-amber-300",
                      label === "Standard" &&
                        "bg-violet-500/10 text-violet-700 dark:text-violet-300",
                      label === "Quick top-up" &&
                        "bg-sky-500/10 text-sky-700 dark:text-sky-300",
                    )}
                  >
                    {label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <form
          className="flex min-w-0 flex-col justify-center rounded-md bg-background p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (customValid && !isPending) {
              setPendingAmount(customValue);
            }
          }}
        >
          <label
            htmlFor="custom-funds-amount"
            className="mb-2 text-xs font-semibold text-foreground"
          >
            Custom amount
          </label>

          <div className="flex min-w-0 gap-2">
            <div className="relative min-w-0 flex-1">
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted-foreground"
              >
                ₹
              </span>
              <Input
                id="custom-funds-amount"
                type="number"
                min={1}
                max={100000}
                step={1}
                inputMode="numeric"
                value={customAmt}
                onChange={(event) => setCustomAmt(event.target.value)}
                placeholder="Enter amount"
                className="h-9 min-w-0 bg-background/90 pl-7 text-sm tabular-nums"
                disabled={isPending}
              />
            </div>

            <Button
              type="submit"
              size="sm"
              disabled={isPending || !customValid}
              className="h-9 shrink-0 gap-1.5 px-3"
            >
              {isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span className="hidden sm:inline">Processing</span>
                </>
              ) : (
                <>
                  <Plus className="h-3.5 w-3.5" />
                  Add funds
                </>
              )}
            </Button>
          </div>

          <p className="mt-1.5 text-[10px] text-muted-foreground">
            Whole rupees only
          </p>
        </form>
      </div>

      <AlertDialog
        open={pendingAmount !== null}
        onOpenChange={(open) => {
          if (!open) setPendingAmount(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm wallet top-up</AlertDialogTitle>
            <AlertDialogDescription>
              Continue with adding{" "}
              <span className="font-semibold text-foreground">
                ₹{pendingAmount?.toLocaleString("en-IN")}
              </span>{" "}
              to your wallet?
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button onClick={confirmRecharge} disabled={isPending}>
              Confirm top-up
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
