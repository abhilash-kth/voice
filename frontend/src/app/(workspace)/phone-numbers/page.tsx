"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Loader2,
  PhoneCall,
  Plus,
  RefreshCw,
  SendHorizontal,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";
import { me, recharge } from "@/lib";
import {
  allocateCallingBalance,
  getKyc,
  getTelephonyOverview,
  setupPhoneAccount,
  syncPhoneAccount,
  type TelephonyOverview,
} from "@/lib/telephony";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import KycPanel from "./components/KycPanel";
import NumberShop, { OwnedNumbers } from "./components/NumberShop";

const inr = (v: unknown) =>
  `₹${(Number(v) || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const inputCls = "h-9 bg-background";

export default function PhoneNumbersPage() {
  const [overview, setOverview] = useState<TelephonyOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [topup, setTopup] = useState("500");
  const [allocate, setAllocate] = useState("100");

  const load = useCallback(async (syncKyc = true) => {
    try {
      const [ov, user] = await Promise.all([
        getTelephonyOverview(),
        me().catch(() => null),
      ]);
      setOverview(ov);
      setName((current) => current || user?.name || ov.account?.name || "");
      setPhone((current) => current || ov.account?.phone || "");
      setError("");
      if (syncKyc && ov.account) {
        try {
          const out = await getKyc();
          setOverview((prev) =>
            prev ? { ...prev, account: out.account, kyc: out.kyc } : prev,
          );
        } catch {
          // Keep the last saved KYC status if the provider is briefly down.
        }
      }
    } catch (e) {
      setError((e as Error).message || "Could not load phone numbers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
    const params = new URLSearchParams(window.location.search);
    if (params.get("kyc") === "returned") {
      toast.info(
        "Returned from DigiLocker. We are checking the provider's verified KYC status now.",
      );
    }
  }, [load]);

  const waitAction = async (fn: () => Promise<string>) => {
    if (busy) return;
    setBusy(true);
    try {
      toast.success(await fn());
      await load(false);
    } catch (e) {
      toast.error((e as Error).message || "Action failed.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading phone numbers…
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Phone Numbers</h1>
        <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-5">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <div>
            <p className="font-medium">Could not load telephony</p>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
            <Button type="button" variant="outline" className="mt-4" onClick={() => void load(false)}>
              Try again
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const account = overview.account;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Phone Numbers</h1>
            {overview.configured ? (
              <Badge variant="outline">Automatic activation</Badge>
            ) : (
              <Badge variant="destructive">Setup required</Badge>
            )}
          </div>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
            Verify once, buy a number, and assign it to an agent. Everything
            happens here — no SIP password, trunk ID, or outside telecom
            dashboard needed.
          </p>
        </div>
        <Link
          href="/agents"
          className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Create or edit agent <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {overview.provider_error && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <p className="text-sm leading-relaxed">
            Live provider rates/status could not be refreshed just now. Saved
            account and number information is shown below; use Refresh later.
          </p>
        </div>
      )}

      {account?.status === "suspended" && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-5">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <p className="text-sm leading-relaxed">
            This telephony account is suspended. Assigned numbers cannot place
            or receive calls until support reactivates the account.
          </p>
        </div>
      )}

      {!overview.configured && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <p className="text-sm leading-relaxed">
            Phone-number setup is waiting for the platform operator to finish
            provider configuration. You can still use browser calling and the
            default outbound trunk where configured.
          </p>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-medium">
            <PhoneCall className="h-4 w-4 text-primary" /> Phone setup
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight">
            {account
              ? account.status === "suspended"
                ? "Suspended"
                : "Ready"
              : "Not started"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {account
              ? `KYC: ${(account.kyc_status || "pending").replace(/_/g, " ")} · ${account.channels_allocated} allocated channels`
              : "Create a managed calling account to begin KYC."}
          </p>
        </section>
        <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Wallet className="h-4 w-4 text-primary" /> App wallet
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight tabular-nums">
            {inr(overview.wallet.balance)}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Used to buy numbers and move calling balance.
          </p>
        </section>
        <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-medium">
            <PhoneCall className="h-4 w-4 text-primary" /> Calling balance
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight tabular-nums">
            {inr(account?.wallet_balance)}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {overview.numbers.length} purchased number
            {overview.numbers.length === 1 ? "" : "s"}
          </p>
        </section>
      </div>

      {!account ? (
        <form
          className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6"
          onSubmit={(e) => {
            e.preventDefault();
            void waitAction(async () => {
              await setupPhoneAccount({
                name: name.trim(),
                phone: phone.trim(),
              });
              return "Phone setup started. Complete KYC next.";
            });
          }}
        >
          <div>
            <h2 className="text-base font-semibold">1. Start phone setup</h2>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              We create a fully managed telecom account in the background. You
              never receive or manage its provider password.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Account name</Label>
              <Input
                required
                value={name}
                disabled={busy}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Mobile number (+91)</Label>
              <Input
                required
                value={phone}
                disabled={busy}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91XXXXXXXXXX"
                className={inputCls}
              />
            </div>
          </div>
          <Button type="submit" disabled={busy || !overview.configured}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Start phone setup
          </Button>
        </form>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <KycPanel kyc={overview.kyc!} onChanged={() => load(false)} />

          <section className="h-fit space-y-5 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
            <div>
              <h3 className="text-base font-semibold">Wallet & calling balance</h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Buy numbers from the app wallet. Move confirmed app-wallet
                funds to calling balance separately when needed.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 rounded-lg border border-border/70 p-4">
                <Label className="text-xs">Add app-wallet funds (₹)</Label>
                <Input
                  type="number"
                  min={1}
                  value={topup}
                  disabled={busy}
                  onChange={(e) => setTopup(e.target.value)}
                  className={inputCls}
                />
                <Button
                  type="button"
                  disabled={busy || Number(topup) <= 0}
                  onClick={() =>
                    void waitAction(async () => {
                      await recharge(Number(topup));
                      return "App wallet updated.";
                    })
                  }
                  className="w-full"
                >
                  <Plus className="h-4 w-4" /> Add funds
                </Button>
                <Link href="/billing" className="block text-center text-xs text-primary underline">
                  View billing history
                </Link>
              </div>
              <div className="space-y-2 rounded-lg border border-border/70 p-4">
                <Label className="text-xs">Move to calling balance (₹)</Label>
                <Input
                  type="number"
                  min={1}
                  value={allocate}
                  disabled={busy}
                  onChange={(e) => setAllocate(e.target.value)}
                  className={inputCls}
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={
                    busy ||
                    Number(allocate) <= 0 ||
                    Number(allocate) > Number(overview.wallet.balance)
                  }
                  onClick={() =>
                    void waitAction(async () => {
                      await allocateCallingBalance(Number(allocate));
                      return "Calling balance updated.";
                    })
                  }
                  className="w-full"
                >
                  <SendHorizontal className="h-4 w-4" /> Move balance
                </Button>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  This does not buy a number; number purchases charge the app
                  wallet at confirmation.
                </p>
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void waitAction(async () => {
                  await syncPhoneAccount();
                  return "Phone account, KYC, and owned numbers refreshed.";
                })
              }
            >
              <RefreshCw className="h-4 w-4" /> Refresh provider status
            </Button>
          </section>
        </div>
      )}

      <NumberShop overview={overview} onChanged={() => load(false)} />
      <OwnedNumbers numbers={overview.numbers} onChanged={() => load(false)} />
    </div>
  );
}
