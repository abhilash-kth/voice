"use client";

import { useCallback, useEffect, useState } from "react";
import {
  RefreshCw,
  Save,
  CheckCircle2,
  XCircle,
  Info,
  Calculator,
  Wallet,
  Gauge,
  IndianRupee,
  Clock,
  Shield,
} from "lucide-react";
import PageHeader, { useBusy } from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import { getBilling, updateBilling, type BillingConfig } from "@/lib/api";
import { fmtINR, toNum } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import RateCalculator from "@/components/RateCalculator";

export default function BillingPage() {
  const [cfg, setCfg] = useState<BillingConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const [serverCost, setServerCost] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [margin, setMargin] = useState("");
  const [topups, setTopups] = useState("");
  const [vsMin, setVsMin] = useState("");
  const [vsMax, setVsMax] = useState("");
  const [vsDefault, setVsDefault] = useState("");

  // Abhilash's changes (rate cards + minimum billed seconds)
  const [assistMin, setAssistMin] = useState("");
  const [announceMin, setAnnounceMin] = useState("");
  const [assistMinSecs, setAssistMinSecs] = useState("");
  const [announceMinSecs, setAnnounceMinSecs] = useState("");

  const hydrate = (c: BillingConfig) => {
    setServerCost(String(c.server_cost_per_min));
    setMinPrice(String(c.min_client_price));
    setMargin(String(c.profit_margin_percent));
    setTopups((c.wallet_topup_amounts || []).join(", "));
    setVsMin(String(c.voice_speed_min));
    setVsMax(String(c.voice_speed_max));
    setVsDefault(String(c.voice_speed_default));

    // Hydrating his changes (with fallbacks to global safe minimums)
    setAssistMin(String(c.assistant_min_per_min ?? c.min_client_price ?? 1));
    setAnnounceMin(
      String(c.announcement_min_per_min ?? c.min_client_price ?? 1),
    );
    setAssistMinSecs(String(c.assistant_min_bill_seconds ?? 0));
    setAnnounceMinSecs(String(c.announcement_min_bill_seconds ?? 0));
  };

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getBilling()
      .then((c) => {
        setCfg(c);
        hydrate(c);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const cost = toNum(serverCost);
  const marginPct = toNum(margin);
  const withMargin = cost * (1 + marginPct / 100);
  const floor = toNum(minPrice);
  const effective = Math.max(withMargin, floor);

  const save = () => {
    const amounts = topups
      .split(",")
      .map((s) => toNum(s.trim()))
      .filter((n) => n > 0);
    const patch: Partial<BillingConfig> = {
      server_cost_per_min: cost,
      min_client_price: floor,
      profit_margin_percent: marginPct,
      wallet_topup_amounts: amounts,
      voice_speed_min: toNum(vsMin),
      voice_speed_max: toNum(vsMax),
      voice_speed_default: toNum(vsDefault),
      // Saving his changes
      assistant_min_per_min: toNum(assistMin),
      announcement_min_per_min: toNum(announceMin),
      assistant_min_bill_seconds: Math.max(0, Math.floor(toNum(assistMinSecs))),
      announcement_min_bill_seconds: Math.max(
        0,
        Math.floor(toNum(announceMinSecs)),
      ),
    };
    run(async () => {
      const out = await updateBilling(patch);
      setCfg(out);
    }, "Billing config saved ✓ (applied dynamically)");
  };

  const valid =
    cost >= 0 &&
    floor >= 0 &&
    marginPct >= 0 &&
    toNum(vsMin) > 0 &&
    toNum(vsMax) >= toNum(vsMin) &&
    toNum(vsDefault) >= toNum(vsMin) &&
    toNum(vsDefault) <= toNum(vsMax) &&
    toNum(assistMin) >= 0 &&
    toNum(announceMin) >= 0 &&
    toNum(assistMinSecs) >= 0 &&
    toNum(announceMinSecs) >= 0 &&
    amountsValid(topups);

  const topupPreview = topups
    .split(",")
    .map((s) => toNum(s.trim()))
    .filter((n) => n > 0);

  return (
    <>
      <PageHeader
        title="Billing config"
        subtitle="Platform pricing — applied dynamically, no redeploy needed"
      >
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw
            className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
          />
          Reset
        </Button>
        <Button size="sm" disabled={busy || !valid || !cfg} onClick={save}>
          {busy ? (
            <>
              <RefreshCw className="mr-2 h-3.5 w-3.5 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Save className="mr-2 h-3.5 w-3.5" />
              Save changes
            </>
          )}
        </Button>
      </PageHeader>

      {(msg || err) && (
        <div
          className={`mb-6 flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium ${
            msg
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "border-destructive/20 bg-destructive/10 text-destructive"
          }`}
        >
          {msg ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0 text-destructive" />
          )}
          <span>{msg || err}</span>
        </div>
      )}

      <StateBox loading={loading} error={error}>
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Column 1: Pricing Controls */}
          <div className="space-y-4">
            {/* Safety Floor Pricing */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="flex flex-row items-center gap-2.5 space-y-0 border-b border-border/60 pb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Calculator className="h-4 w-4" />
                </div>
                <CardTitle className="text-sm font-semibold">
                  Safety Floor Pricing
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <Field
                  label="Your cost ₹ / min"
                  hint="Infra baseline (telephony + compute). Not shown to users."
                >
                  <Input
                    className="h-9 tabular-nums"
                    type="number"
                    step="0.01"
                    min="0"
                    value={serverCost}
                    onChange={(e) => setServerCost(e.target.value)}
                  />
                </Field>

                <Field
                  label="Profit margin %"
                  hint="Added on top of your cost to compute customer prices."
                >
                  <Input
                    className="h-9 tabular-nums"
                    type="number"
                    step="1"
                    min="0"
                    value={margin}
                    onChange={(e) => setMargin(e.target.value)}
                  />
                </Field>

                <Field
                  label="Minimum safety price ₹ / min"
                  hint="Floor — customers never pay less than this per minute on any model."
                >
                  <Input
                    className="h-9 tabular-nums"
                    type="number"
                    step="0.01"
                    min="0"
                    value={minPrice}
                    onChange={(e) => setMinPrice(e.target.value)}
                  />
                </Field>

                <div className="flex items-start gap-2.5 rounded-lg border border-border/60 bg-muted/20 px-3.5 py-3">
                  <IndianRupee className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    <span className="font-semibold text-foreground">
                      Live preview:
                    </span>{" "}
                    a model costing you {fmtINR(cost)}/min bills customers at{" "}
                    <span className="font-bold tabular-nums text-foreground">
                      {fmtINR(effective)}/min
                    </span>
                    {floor > withMargin
                      ? " (floor price applied)"
                      : " (cost + margin)"}
                    .
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* Customer Rate Card Per Mode */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="flex flex-row items-center gap-2.5 space-y-0 border-b border-border/60 pb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Shield className="h-4 w-4" />
                </div>
                <CardTitle className="text-sm font-semibold">
                  Customer Rate Card Minima
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Assistant Min ₹/min"
                    hint="Rate floor for assistants"
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.01"
                      min="0"
                      value={assistMin}
                      onChange={(e) => setAssistMin(e.target.value)}
                    />
                  </Field>
                  <Field
                    label="Announcement Min ₹/min"
                    hint="Rate floor for announcements"
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.01"
                      min="0"
                      value={announceMin}
                      onChange={(e) => setAnnounceMin(e.target.value)}
                    />
                  </Field>
                </div>
              </CardContent>
            </Card>

            {/* Enterprise Minimum Billed Duration */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="flex flex-row items-center gap-2.5 space-y-0 border-b border-border/60 pb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Clock className="h-4 w-4" />
                </div>
                <CardTitle className="text-sm font-semibold">
                  Minimum Billed Duration (Seconds)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Enterprise billing: a call shorter than the minimum still
                  bills the full minimum duration. Infra costs always use the{" "}
                  <b className="text-foreground">actual</b> duration — only the
                  customer charge is floored. Use{" "}
                  <b className="text-foreground">0 to bill actual duration.</b>
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Assistant Minimum Secs"
                    hint="Short assistant calls floor here."
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="1"
                      min="0"
                      value={assistMinSecs}
                      onChange={(e) => setAssistMinSecs(e.target.value)}
                    />
                  </Field>
                  <Field
                    label="Announcement Minimum Secs"
                    hint="Short announcement calls floor here."
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="1"
                      min="0"
                      value={announceMinSecs}
                      onChange={(e) => setAnnounceMinSecs(e.target.value)}
                    />
                  </Field>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Column 2: Other configurations */}
          <div className="space-y-4">
            {/* Wallet top-ups */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="flex flex-row items-center gap-2.5 space-y-0 border-b border-border/60 pb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Wallet className="h-4 w-4" />
                </div>
                <CardTitle className="text-sm font-semibold">
                  Wallet top-ups
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <Field
                  label="Amounts offered in the dashboard"
                  hint="₹, comma-separated. Customers pick one when recharging."
                >
                  <Input
                    className="h-9"
                    value={topups}
                    onChange={(e) => setTopups(e.target.value)}
                    placeholder="100, 250, 500, 1000"
                  />
                </Field>
                {topupPreview.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {topupPreview.map((n, i) => (
                      <Badge
                        key={i}
                        variant="outline"
                        className="border-emerald-500/20 bg-emerald-500/10 tabular-nums text-emerald-700 dark:text-emerald-400"
                      >
                        {fmtINR(n)}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Voice speed */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="flex flex-row items-center gap-2.5 space-y-0 border-b border-border/60 pb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Gauge className="h-4 w-4" />
                </div>
                <CardTitle className="text-sm font-semibold">
                  Voice speed (TTS)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Min">
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.1"
                      min="0.1"
                      value={vsMin}
                      onChange={(e) => setVsMin(e.target.value)}
                    />
                  </Field>
                  <Field label="Max">
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.1"
                      min="0.1"
                      value={vsMax}
                      onChange={(e) => setVsMax(e.target.value)}
                    />
                  </Field>
                  <Field label="Default">
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.1"
                      min="0.1"
                      value={vsDefault}
                      onChange={(e) => setVsDefault(e.target.value)}
                    />
                  </Field>
                </div>

                {!valid && vsMin && vsMax && (
                  <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      Speeds must satisfy: 0 &lt; min ≤ default ≤ max.
                    </span>
                  </div>
                )}

                <Separator className="bg-border/60" />

                <div className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                  <p>
                    Range enforced in the customer agent config; default
                    pre-selects the slider.
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
        <RateCalculator />
      </StateBox>
    </>
  );
}

function amountsValid(topups: string): boolean {
  const parts = topups
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return parts.length > 0 && parts.every((p) => Number(p) > 0);
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
      {hint && (
        <p className="text-[11px] leading-relaxed text-muted-foreground/70">
          {hint}
        </p>
      )}
    </div>
  );
}
