"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  XCircle,
} from "lucide-react";
import PageHeader, { useBusy } from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import {
  createPlan,
  deletePlan,
  getBilling,
  listPlans,
  listSubscriptions,
  updateBilling,
  updatePlan,
  type PlanTier,
  type SubscriptionRow,
} from "@/lib/billing";
import { fmtINR, toNum } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanTier[]>([]);
  const [subs, setSubs] = useState<SubscriptionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const [kind, setKind] = useState<"capacity" | "kb_pack">("capacity");
  const [label, setLabel] = useState("");
  const [units, setUnits] = useState("");
  const [faqs, setFaqs] = useState("");
  const [price, setPrice] = useState("");
  const [linePrice, setLinePrice] = useState("");
  const [teleRent, setTeleRent] = useState("");
  const [edits, setEdits] = useState<Record<string, PlanTier>>({});

  const load = useCallback(() => {
    setLoading(true);
    setError("");

    Promise.all([listPlans(), listSubscriptions(), getBilling()])
      .then(([plansResult, subscriptionsResult, billing]) => {
        setPlans(plansResult.items);
        setSubs(subscriptionsResult.items);
        setLinePrice(String(billing.concurrency_line_price_per_month ?? 0));
        setTeleRent(String(billing.telephony_rent_per_month ?? 0));
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const edited = (plan: PlanTier) => edits[plan.id] || plan;

  const setEdit = (plan: PlanTier, patch: Partial<PlanTier>) => {
    setEdits((current) => ({
      ...current,
      [plan.id]: { ...(current[plan.id] || plan), ...patch },
    }));
  };

  const add = () =>
    run(async () => {
      await createPlan({
        kind,
        label: label.trim(),
        units: Math.trunc(toNum(units)),
        faqs: kind === "kb_pack" ? Math.trunc(toNum(faqs)) : 0,
        price_per_month: toNum(price),
        enabled: true,
        sort_order: plans.length,
      });

      setLabel("");
      setUnits("");
      setFaqs("");
      setPrice("");
      load();
    }, "Plan added ✓");

  const saveRow = (plan: PlanTier) =>
    run(async () => {
      const current = edited(plan);

      await updatePlan(plan.id, {
        label: current.label,
        units: current.units,
        faqs: current.faqs,
        price_per_month: Number(current.price_per_month),
        enabled: current.enabled,
        sort_order: current.sort_order,
      });

      setEdits((currentEdits) => {
        const next = { ...currentEdits };
        delete next[plan.id];
        return next;
      });

      load();
    }, "Plan saved ✓");

  const saveGlobals = () =>
    run(async () => {
      await updateBilling({
        concurrency_line_price_per_month: toNum(linePrice),
        telephony_rent_per_month: toNum(teleRent),
      });
    }, "Monthly prices saved ✓");

  const deleteRow = (planId: string) =>
    run(async () => {
      await deletePlan(planId);
      load();
    }, "Plan deleted ✓");

  return (
    <>
      <PageHeader
        title="Monthly plans"
        subtitle="What customers subscribe to before building agents"
      >
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw
            className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
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
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0" />
          )}
          <span>{msg || err}</span>
        </div>
      )}

      <StateBox loading={loading} error={error}>
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="border-b border-border/60 pb-4">
                <CardTitle className="text-sm font-semibold">
                  Concurrency and telephony (₹ / month)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field
                    label="Extra concurrent line ₹/month"
                    hint="The first line is free; each extra line costs this per month."
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      min="0"
                      step="1"
                      value={linePrice}
                      onChange={(e) => setLinePrice(e.target.value)}
                    />
                  </Field>

                  <Field
                    label="Telephony rent ₹/month"
                    hint="Monthly number or telephony access rent."
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      min="0"
                      step="1"
                      value={teleRent}
                      onChange={(e) => setTeleRent(e.target.value)}
                    />
                  </Field>
                </div>

                <Button size="sm" disabled={busy} onClick={saveGlobals}>
                  <Save className="mr-2 h-3.5 w-3.5" />
                  Save monthly prices
                </Button>
              </CardContent>
            </Card>

            <Card className="border-border/60 shadow-sm">
              <CardHeader className="border-b border-border/60 pb-4">
                <CardTitle className="text-sm font-semibold">
                  Add a plan
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Type">
                    <select
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value={kind}
                      onChange={(e) =>
                        setKind(e.target.value as "capacity" | "kb_pack")
                      }
                    >
                      <option value="capacity">Agent plan</option>
                      <option value="kb_pack">Knowledge-base pack</option>
                    </select>
                  </Field>

                  <Field label="Label">
                    <Input
                      className="h-9"
                      value={label}
                      onChange={(e) => setLabel(e.target.value)}
                      placeholder={
                        kind === "capacity" ? "3-agent plan" : "KB +100k"
                      }
                    />
                  </Field>

                  <Field
                    label={
                      kind === "capacity"
                        ? "Agents allowed"
                        : "Extra KB characters"
                    }
                  >
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      min="0"
                      value={units}
                      onChange={(e) => setUnits(e.target.value)}
                      placeholder={kind === "capacity" ? "3" : "100000"}
                    />
                  </Field>

                  {kind === "kb_pack" && (
                    <Field label="Extra FAQs">
                      <Input
                        className="h-9 tabular-nums"
                        type="number"
                        min="0"
                        value={faqs}
                        onChange={(e) => setFaqs(e.target.value)}
                        placeholder="100"
                      />
                    </Field>
                  )}

                  <Field label="Price ₹ / month">
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      min="0"
                      step="1"
                      value={price}
                      onChange={(e) => setPrice(e.target.value)}
                      placeholder="499"
                    />
                  </Field>
                </div>

                <Button
                  size="sm"
                  disabled={busy || !label.trim() || toNum(units) <= 0}
                  onClick={add}
                >
                  <Plus className="mr-2 h-3.5 w-3.5" />
                  Add plan
                </Button>
              </CardContent>
            </Card>
          </div>

          <Card className="border-border/60 shadow-sm">
            <CardHeader className="border-b border-border/60 pb-4">
              <CardTitle className="text-sm font-semibold">
                Plans on sale
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-5">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Type</th>
                      <th className="px-3 py-2 font-medium">Label</th>
                      <th className="px-3 py-2 text-right font-medium">
                        Allowance
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        ₹/month
                      </th>
                      <th className="px-3 py-2 font-medium">Enabled</th>
                      <th className="px-3 py-2 text-right font-medium">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {plans.map((plan) => {
                      const current = edited(plan);

                      return (
                        <tr
                          key={plan.id}
                          className="border-b border-border/40 last:border-0"
                        >
                          <td className="px-3 py-3">
                            <Badge variant="outline">
                              {plan.kind === "capacity" ? "Agents" : "KB pack"}
                            </Badge>
                          </td>
                          <td className="px-3 py-3">
                            <Input
                              className="h-8 min-w-36"
                              value={current.label}
                              onChange={(e) =>
                                setEdit(plan, { label: e.target.value })
                              }
                            />
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center justify-end gap-2">
                              <Input
                                className="h-8 w-24 text-right tabular-nums"
                                type="number"
                                min="0"
                                value={current.units}
                                onChange={(e) =>
                                  setEdit(plan, {
                                    units: Math.trunc(Number(e.target.value)),
                                  })
                                }
                              />
                              <span className="whitespace-nowrap text-xs text-muted-foreground">
                                {plan.kind === "capacity" ? "agents" : "chars"}
                                {plan.kind === "kb_pack" && current.faqs > 0
                                  ? ` + ${current.faqs} FAQs`
                                  : ""}
                              </span>
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <Input
                              className="ml-auto h-8 w-24 text-right tabular-nums"
                              type="number"
                              min="0"
                              value={current.price_per_month}
                              onChange={(e) =>
                                setEdit(plan, {
                                  price_per_month: Number(e.target.value),
                                })
                              }
                            />
                          </td>
                          <td className="px-3 py-3">
                            <Button
                              type="button"
                              size="sm"
                              variant={
                                current.enabled ? "secondary" : "outline"
                              }
                              disabled={busy}
                              onClick={() =>
                                setEdit(plan, { enabled: !current.enabled })
                              }
                            >
                              {current.enabled ? "On" : "Off"}
                            </Button>
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex justify-end gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => saveRow(plan)}
                              >
                                <Save className="mr-1.5 h-3.5 w-3.5" />
                                Save
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="text-destructive hover:text-destructive"
                                disabled={busy}
                                onClick={() => deleteRow(plan.id)}
                              >
                                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                                Delete
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}

                    {plans.length === 0 && (
                      <tr>
                        <td
                          colSpan={6}
                          className="py-6 text-center text-sm text-muted-foreground"
                        >
                          No plans yet — add an agent plan or knowledge-base
                          pack above.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/60 shadow-sm">
            <CardHeader className="border-b border-border/60 pb-4">
              <CardTitle className="text-sm font-semibold">
                Subscribers
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-5">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Customer</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 text-right font-medium">
                        Agents
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        Lines
                      </th>
                      <th className="px-3 py-2 font-medium">Telephony</th>
                      <th className="px-3 py-2 text-right font-medium">
                        ₹/month
                      </th>
                      <th className="px-3 py-2 font-medium">Renews</th>
                    </tr>
                  </thead>
                  <tbody>
                    {subs.map((subscription) => (
                      <tr
                        key={subscription.user_id}
                        className="border-b border-border/40 last:border-0"
                      >
                        <td className="px-3 py-3">
                          <div className="text-sm font-medium">
                            {subscription.user_name ||
                              subscription.user_email ||
                              subscription.user_id.slice(0, 10)}
                          </div>
                          {subscription.user_name &&
                            subscription.user_email && (
                              <div className="text-xs text-muted-foreground">
                                {subscription.user_email}
                              </div>
                            )}
                        </td>
                        <td className="px-3 py-3">
                          <Badge
                            variant={
                              subscription.status === "active"
                                ? "default"
                                : subscription.status === "past_due"
                                  ? "destructive"
                                  : "secondary"
                            }
                          >
                            {subscription.status}
                          </Badge>
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums">
                          {subscription.agent_limit}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums">
                          {subscription.concurrency_lines}
                        </td>
                        <td className="px-3 py-3">
                          {subscription.telephony_rented ? "Rented" : "—"}
                        </td>
                        <td className="px-3 py-3 text-right font-medium tabular-nums">
                          {fmtINR(subscription.monthly_total)}
                        </td>
                        <td className="px-3 py-3 text-xs text-muted-foreground">
                          {subscription.renews_at
                            ? subscription.renews_at.slice(0, 10)
                            : "—"}
                        </td>
                      </tr>
                    ))}

                    {subs.length === 0 && (
                      <tr>
                        <td
                          colSpan={7}
                          className="py-6 text-center text-sm text-muted-foreground"
                        >
                          No subscribers yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      </StateBox>
    </>
  );
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
