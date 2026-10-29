"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpCircle,
  Loader2,
  PhoneCall,
  RefreshCw,
  Search,
  ShoppingCart,
} from "lucide-react";
import { toast } from "sonner";
import {
  confirmPurchase,
  quoteChannelUpgrade,
  quoteNumber,
  retryProvision,
  searchNumbers,
  syncInbound,
  upgradePhoneChannels,
  type AvailableNumber,
  type ChannelUpgradeQuote,
  type PhoneNumberRecord,
  type PhonePurchase,
  type TelephonyOverview,
} from "@/lib/telephony";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const inr = (v: unknown) =>
  `₹${(Number(v) || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const selectCls =
  "flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm";

function statusVariant(status: string) {
  if (status === "active") return "default" as const;
  if (status === "failed" || status === "needs_review") return "destructive" as const;
  return "secondary" as const;
}

export default function NumberShop({
  overview,
  onChanged,
}: {
  overview: TelephonyOverview;
  onChanged: () => Promise<void> | void;
}) {
  const [didType, setDidType] = useState("2");
  const [query, setQuery] = useState("");
  const [months, setMonths] = useState(1);
  const [channels, setChannels] = useState(() =>
    Math.min(
      20,
      Math.max(
        1,
        Number(overview.plan_channels || 1),
        Number(overview.account?.channels_allocated || 0),
      ),
    ),
  );
  const channelsTouched = useRef(false);
  const [results, setResults] = useState<AvailableNumber[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [busy, setBusy] = useState(false);
  const [purchase, setPurchase] = useState<PhonePurchase | null>(
    overview.latest_purchase,
  );
  const [accept, setAccept] = useState(false);
  const idempotency = useRef("");
  const kycVerified = overview.kyc?.status === "verified";
  const accountReady = Boolean(overview.account);

  useEffect(() => {
    setPurchase(overview.latest_purchase);
  }, [overview.latest_purchase]);

  useEffect(() => {
    if (channelsTouched.current) return;
    setChannels(
      Math.min(
        20,
        Math.max(
          1,
          Number(overview.plan_channels || 1),
          Number(overview.account?.channels_allocated || 0),
        ),
      ),
    );
  }, [overview.plan_channels, overview.account?.channels_allocated]);

  const types =
    overview.provider?.did_type_rates &&
    overview.provider.did_type_rates.length > 0
      ? overview.provider.did_type_rates
      : [
          { type_id: "2", name: "Direct number", monthly_rate: 0 },
          { type_id: "3", name: "Landline", monthly_rate: 0 },
        ];

  useEffect(() => {
    if (types.length > 0 && !types.some((t) => t.type_id === didType)) {
      setDidType(types[0].type_id);
    }
  }, [didType, types]);

  const search = async (nextPage = 1) => {
    if (busy) return;
    setBusy(true);
    try {
      const out = await searchNumbers({
        type: didType,
        months,
        number: query.trim() || undefined,
        page: nextPage,
      });
      setResults(out.items);
      setPage(out.page);
      setTotalPages(Math.max(1, Math.ceil((out.total || out.items.length) / 25)));
      if (out.items.length === 0) {
        toast.info("No available numbers matched — try another pattern.");
      }
    } catch (e) {
      toast.error((e as Error).message || "Number search failed.");
    } finally {
      setBusy(false);
    }
  };

  const quote = async (did: AvailableNumber) => {
    if (busy) return;
    if (!idempotency.current) idempotency.current = crypto.randomUUID();
    setBusy(true);
    try {
      const out = await quoteNumber({
        did_id: did.id,
        number: did.number,
        months,
        channels,
        idempotency_key: idempotency.current,
      });
      setPurchase(out.purchase);
      setAccept(false);
      toast.success("Price quoted — confirm before the quote expires.");
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Could not quote this number.");
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!purchase || busy) return;
    setBusy(true);
    try {
      const out = await confirmPurchase(purchase.id);
      setPurchase(out.purchase);
      idempotency.current = "";
      if (out.purchase.warning) toast.warning(out.purchase.warning);
      else if (out.purchase.state === "needs_review") {
        toast.warning(
          "The provider outcome was uncertain. Do not buy again; support will reconcile it.",
        );
      } else {
        toast.success("Purchase confirmed. Automatic activation has started.");
      }
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Purchase could not be confirmed.");
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  const expires = purchase?.expires_at
    ? new Date(purchase.expires_at).toLocaleTimeString("en-IN")
    : null;
  const quoted = purchase?.state === "quoted";
  const enough =
    Number(overview.wallet.balance) >= Number(purchase?.quote_total || 0);

  return (
    <section className="space-y-5 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <ShoppingCart className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Buy a phone number</h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            The exact provider price is shown before you confirm. You never
            see SIP passwords or trunk settings; activation is automatic.
          </p>
        </div>
      </div>

      {!accountReady ? (
        <p className="rounded-lg bg-muted/50 p-4 text-sm text-muted-foreground">
          Start phone setup above before browsing numbers.
        </p>
      ) : !kycVerified ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-300">
          You can browse available numbers now. Complete KYC before buying.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <div className="space-y-1.5">
          <Label className="text-xs">Number type</Label>
          <select
            value={didType}
            disabled={busy || !accountReady}
            onChange={(e) => setDidType(e.target.value)}
            className={selectCls}
          >
            {types.map((t) => (
              <option key={t.type_id} value={t.type_id}>
                {t.name}
                {t.monthly_rate ? ` · ${inr(t.monthly_rate)}/mo` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5 lg:col-span-2">
          <Label className="text-xs">Find digits (optional)</Label>
          <Input
            value={query}
            disabled={busy || !accountReady}
            onChange={(e) => setQuery(e.target.value.replace(/[^0-9+]/g, ""))}
            placeholder="e.g. 9876 or ending digits"
            className="h-9 bg-background tabular-nums"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Billing period</Label>
          <select
            value={months}
            disabled={busy}
            onChange={(e) => setMonths(Number(e.target.value))}
            className={selectCls}
          >
            {[1, 3, 6, 12].map((m) => (
              <option key={m} value={m}>
                {m} month{m > 1 ? "s" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Channels</Label>
          <Input
            type="number"
            min={1}
            max={20}
            value={channels}
            disabled={busy}
            onChange={(e) => {
              channelsTouched.current = true;
              setChannels(Number(e.target.value));
            }}
            className="h-9 bg-background tabular-nums"
          />
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            Plan includes {Math.max(1, Number(overview.plan_channels || 1))};
            provider account has{" "}
            {Number(overview.account?.channels_allocated || 0)} allocated.
            Extra channels are priced in the provider quote.
          </p>
        </div>
      </div>
      <Button
        type="button"
        disabled={busy || !accountReady}
        onClick={() => void search(1)}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        Search available numbers
      </Button>

      {results.length > 0 && (
        <div className="space-y-3">
          <ul className="grid gap-2 sm:grid-cols-2">
            {results.map((did) => (
              <li
                key={did.id || did.number}
                className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-background px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-sm font-semibold tabular-nums">
                    {did.number}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {did.monthly_rate
                      ? `${inr(did.monthly_rate)}/month`
                      : did.type_label || "Price confirmed at quote"}
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || !kycVerified}
                  onClick={() => void quote(did)}
                >
                  Get price
                </Button>
              </li>
            ))}
          </ul>
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || page <= 1}
                  onClick={() => void search(page - 1)}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || page >= totalPages}
                  onClick={() => void search(page + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {purchase && (
        <div className="space-y-3 rounded-lg border border-primary/25 bg-primary/5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold">Latest number purchase</p>
              <p className="font-mono text-lg font-bold tabular-nums">
                {purchase.number || "Number pending provider confirmation"}
              </p>
            </div>
            <Badge variant={statusVariant(purchase.state)}>
              {purchase.state.replace("_", " ")}
            </Badge>
          </div>
          <div className="grid gap-2 text-sm sm:grid-cols-3">
            <p>
              Total: <strong className="tabular-nums">{inr(purchase.quote_total)}</strong>
            </p>
            <p>
              Monthly: <strong className="tabular-nums">{inr(purchase.monthly_rate)}</strong>
            </p>
            <p>
              Period: <strong>{purchase.months} month</strong> · Channels:{" "}
              <strong>{purchase.channels}</strong>
            </p>
          </div>
          {expires && quoted && (
            <p className="text-sm text-muted-foreground">
              Quote expires at {expires}. You are charged only after
              confirming, from your app wallet.
            </p>
          )}
          {purchase.warning && (
            <p className="rounded bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
              {purchase.warning}
            </p>
          )}
          {purchase.error && (
            <p className="rounded bg-destructive/10 p-3 text-sm text-destructive">
              {purchase.error}
            </p>
          )}
          {quoted && (
            <>
              {purchase.confirmation_available === false && (
                <p className="rounded bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
                  This quote can no longer be confirmed (it may have expired).
                  Search and quote the number again.
                </p>
              )}
              <label className="flex items-start gap-2 text-sm leading-relaxed">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={accept}
                  disabled={busy}
                  onChange={(e) => setAccept(e.target.checked)}
                />
                I accept automatic renewal at the quoted rate while my app
                wallet has sufficient balance.
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  disabled={
                    busy ||
                    !accept ||
                    purchase.confirmation_available === false ||
                    !kycVerified ||
                    !enough
                  }
                  onClick={() => void confirm()}
                >
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Confirm purchase
                </Button>
                {!enough && (
                  <p className="text-sm text-muted-foreground">
                    App wallet balance {inr(overview.wallet.balance)} is
                    below the quote.{" "}
                    <Link className="text-primary underline" href="/billing">
                      Add funds
                    </Link>
                  </p>
                )}
              </div>
            </>
          )}
          {purchase.state === "needs_review" && (
            <p className="text-sm font-medium">
              Do not buy again. Support will reconcile this purchase and your
              wallet; the provider response was uncertain.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export function OwnedNumbers({
  numbers,
  onChanged,
}: {
  numbers: PhoneNumberRecord[];
  onChanged: () => Promise<void> | void;
}) {
  const [busyId, setBusyId] = useState("");
  const [channelTargets, setChannelTargets] = useState<Record<string, number>>(
    {},
  );
  const [channelQuotes, setChannelQuotes] = useState<
    Record<string, ChannelUpgradeQuote>
  >({});

  const getChannelQuote = async (n: PhoneNumberRecord) => {
    const target = Math.max(
      n.channels + 1,
      Math.trunc(channelTargets[n.id] || n.channels + 1),
    );
    setBusyId(n.id);
    try {
      const out = await quoteChannelUpgrade(n.id, target);
      setChannelQuotes((current) => ({ ...current, [n.id]: out.quote }));
    } catch (e) {
      toast.error((e as Error).message || "Could not price channel upgrade.");
    } finally {
      setBusyId("");
    }
  };

  const confirmChannelUpgrade = async (n: PhoneNumberRecord) => {
    const quote = channelQuotes[n.id];
    if (!quote) return;
    setBusyId(n.id);
    try {
      const out = await upgradePhoneChannels(n.id, quote);
      setChannelQuotes((current) => {
        const next = { ...current };
        delete next[n.id];
        return next;
      });
      toast.success(
        `${out.phone_number.number} now has ${out.phone_number.channels} channels. ` +
          `Charged ${inr(out.charged_now)} now; edit the assigned agent and set ` +
          `Max concurrent calls to ${out.phone_number.channels}.`,
      );
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Channel upgrade failed.");
      await onChanged();
    } finally {
      setBusyId("");
    }
  };

  const run = async (n: PhoneNumberRecord, kind: "retry" | "sync") => {
    setBusyId(n.id);
    try {
      const out =
        kind === "retry" ? await retryProvision(n.id) : await syncInbound(n.id);
      if (out.phone_number.status === "active") {
        toast.success("Phone number is active.");
      } else if (out.phone_number.last_error) {
        toast.warning(out.phone_number.last_error);
      } else {
        toast.success("Phone number updated.");
      }
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Phone-number action failed.");
      await onChanged();
    } finally {
      setBusyId("");
    }
  };

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <PhoneCall className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Your phone numbers</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Assign an active number while creating or editing an agent. SIP
            credentials stay hidden and are managed for you.
          </p>
        </div>
      </div>
      {numbers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No phone numbers yet. Buy your first number above.
        </div>
      ) : (
        <ul className="space-y-3">
          {numbers.map((n) => (
            <li
              key={n.id}
              className="space-y-3 rounded-lg border border-border/70 bg-background p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-mono text-base font-bold tabular-nums">{n.number}</p>
                  <p className="text-xs text-muted-foreground">
                    {n.channels} channel{n.channels === 1 ? "" : "s"}
                    {n.expires_at
                      ? ` · expires ${new Date(n.expires_at).toLocaleDateString("en-IN")}`
                      : ""}
                  </p>
                </div>
                <Badge variant={statusVariant(n.status)}>
                  {n.status.replace("_", " ")}
                </Badge>
              </div>
              {n.status !== "active" && (
                <p className="text-sm text-muted-foreground">
                  Activation step: {(n.provisioning_step || "starting").replace("_", " ")}
                  {n.last_error ? ` — ${n.last_error}` : ""}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                {n.status !== "active" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busyId === n.id}
                    onClick={() => void run(n, "retry")}
                  >
                    {busyId === n.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    Retry activation
                  </Button>
                )}
                {n.status === "active" && (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busyId === n.id}
                      onClick={() => void run(n, "sync")}
                    >
                      Sync inbound routing
                    </Button>
                    <Link
                      href="/agents"
                      className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                    >
                      Assign to an agent
                    </Link>
                  </>
                )}
              </div>

              {n.status === "active" && (
                <div className="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-3">
                  <div>
                    <p className="text-sm font-semibold">
                      Increase channels on this same number
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      One channel carries one simultaneous call. Channels
                      already included in your plan or provider allocation
                      are not charged again.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Total channels</Label>
                      <Input
                        type="number"
                        min={n.channels + 1}
                        max={100}
                        value={channelTargets[n.id] ?? n.channels + 1}
                        disabled={busyId === n.id}
                        onChange={(e) => {
                          const target = Number(e.target.value);
                          setChannelTargets((current) => ({
                            ...current,
                            [n.id]: target,
                          }));
                          setChannelQuotes((current) => {
                            const next = { ...current };
                            delete next[n.id];
                            return next;
                          });
                        }}
                        className="h-9 w-36 bg-background tabular-nums"
                      />
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={
                        busyId === n.id ||
                        Number(channelTargets[n.id] ?? n.channels + 1) <=
                          n.channels
                      }
                      onClick={() => void getChannelQuote(n)}
                    >
                      {busyId === n.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <ArrowUpCircle className="h-3.5 w-3.5" />
                      )}
                      Get upgrade price
                    </Button>
                  </div>

                  {channelQuotes[n.id] && (
                    <div className="space-y-3 rounded-lg border border-primary/25 bg-primary/5 p-3 text-sm">
                      <div className="grid gap-2 sm:grid-cols-3">
                        <p>
                          Added to number:{" "}
                          <strong>
                            {channelQuotes[n.id].added_phone_channels}
                          </strong>
                        </p>
                        <p>
                          Billable new channels:{" "}
                          <strong>
                            {channelQuotes[n.id].billable_added_channels}
                          </strong>
                        </p>
                        <p>
                          Per channel:{" "}
                          <strong>
                            {inr(
                              channelQuotes[n.id].channel_price_per_month,
                            )}
                            /month
                          </strong>
                        </p>
                        <p>
                          Due now:{" "}
                          <strong>{inr(channelQuotes[n.id].due_now)}</strong>
                        </p>
                        <p>
                          Monthly increase:{" "}
                          <strong>
                            {inr(channelQuotes[n.id].monthly_increment)}
                          </strong>
                        </p>
                        <p>
                          New plan total:{" "}
                          <strong>
                            {inr(channelQuotes[n.id].new_monthly_total)}/month
                          </strong>
                        </p>
                      </div>
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        {channelQuotes[n.id].billable_added_channels === 0
                          ? "This target is already covered by your plan/provider allocation, so there is no channel charge."
                          : `Due now is prorated for the remaining ${channelQuotes[n.id].remaining_days} day(s) in this subscription cycle. The full monthly increase applies from the next renewal.`}{" "}
                        Wallet balance: {inr(channelQuotes[n.id].wallet_balance)}.
                      </p>
                      <Button
                        type="button"
                        size="sm"
                        disabled={
                          busyId === n.id ||
                          !channelQuotes[n.id].sufficient_balance
                        }
                        onClick={() => void confirmChannelUpgrade(n)}
                      >
                        {busyId === n.id && (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        )}
                        Confirm &amp; upgrade to{" "}
                        {channelQuotes[n.id].target_channels} channels
                      </Button>
                      {!channelQuotes[n.id].sufficient_balance && (
                        <p className="text-xs font-medium text-destructive">
                          Recharge your app wallet before confirming.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
