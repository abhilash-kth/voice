"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Pencil,
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
  createSubscription,
  deletePlan,
  deleteSubscription,
  getAdminSubscription,
  getBilling,
  listPlans,
  listSubscriptions,
  updateBilling,
  updatePlan,
  updateSubscription,
  type PlanTier,
  type SubscriptionCreate,
  type SubscriptionRow,
} from "@/lib/billing";
import { listUsers, type ApiUser } from "@/lib/api";
import { fmtINR, toNum } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type SubscriptionForm = SubscriptionCreate;

const blankSubscription: SubscriptionForm = {
  user_id: "",
  status: "active",
  agent_limit: 0,
  channels: 1,
  telephony_rented: false,
  kb_extra_chars: 0,
  kb_extra_faqs: 0,
  monthly_total: 0,
  renews_at: "",
};

const subscriptionToForm = (row: SubscriptionRow): SubscriptionForm => ({
  user_id: row.user_id,
  status:
    row.status === "past_due" || row.status === "inactive"
      ? row.status
      : "active",
  agent_limit: row.agent_limit,
  channels: row.plan_channels ?? row.channels ?? row.concurrency_lines ?? 1,
  telephony_rented: row.telephony_rented,
  kb_extra_chars: row.kb_extra_chars ?? row.kb_char_limit ?? 0,
  kb_extra_faqs: row.kb_extra_faqs ?? row.kb_faq_limit ?? 0,
  monthly_total: row.monthly_total,
  renews_at: row.renews_at ? row.renews_at.slice(0, 10) : "",
});

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanTier[]>([]);
  const [subs, setSubs] = useState<SubscriptionRow[]>([]);
  const [users, setUsers] = useState<ApiUser[]>([]);
  const [newSubscription, setNewSubscription] =
    useState<SubscriptionForm>(blankSubscription);
  const [subscriptionEdits, setSubscriptionEdits] = useState<
    Record<string, SubscriptionForm>
  >({});
  const [editingSubscription, setEditingSubscription] = useState("");
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

    Promise.all([
      listPlans(),
      listSubscriptions(),
      getBilling(),
      listUsers({ page_size: 100 }).catch(() => ({ items: [] as ApiUser[] })),
    ])
      .then(([plansResult, subscriptionsResult, billing, usersResult]) => {
        setPlans(plansResult.items);
        setSubs(subscriptionsResult.items);
        setUsers(usersResult.items);
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

  const editedSubscription = (row: SubscriptionRow) =>
    subscriptionEdits[row.user_id] || subscriptionToForm(row);

  const setSubscriptionEdit = (
    row: SubscriptionRow,
    patch: Partial<SubscriptionForm>,
  ) =>
    setSubscriptionEdits((current) => ({
      ...current,
      [row.user_id]: {
        ...(current[row.user_id] || subscriptionToForm(row)),
        ...patch,
      },
    }));

  const suggestedMonthlyTotal = (row: SubscriptionRow) => {
    if (Number(row.monthly_total || 0) > 0) return Number(row.monthly_total);

    // Older purchased rows can have monthly_total=0 because plan prices
    // were not stored correctly. Only prefill when the stored agent/KB
    // allowances identify exactly one current DB plan price; never guess
    // between multiple plans with the same allowance.
    let total = 0;
    if (row.agent_limit > 0) {
      const prices = Array.from(
        new Set(
          plans
            .filter(
              (plan) =>
                plan.kind === "capacity" && plan.units === row.agent_limit,
            )
            .map((plan) => Number(plan.price_per_month || 0)),
        ),
      );
      if (prices.length !== 1) return 0;
      total += prices[0];
    }

    const kbChars = row.kb_extra_chars ?? row.kb_char_limit ?? 0;
    const kbFaqs = row.kb_extra_faqs ?? row.kb_faq_limit ?? 0;
    if (kbChars > 0 || kbFaqs > 0) {
      const prices = Array.from(
        new Set(
          plans
            .filter(
              (plan) =>
                plan.kind === "kb_pack" &&
                plan.units === kbChars &&
                plan.faqs === kbFaqs,
            )
            .map((plan) => Number(plan.price_per_month || 0)),
        ),
      );
      if (prices.length !== 1) return 0;
      total += prices[0];
    }

    total +=
      Math.max(Number(row.plan_channels ?? row.channels ?? 1) - 1, 0) *
      toNum(linePrice);
    if (row.telephony_rented) total += toNum(teleRent);
    return Math.round(total * 100) / 100;
  };

  const startEditSubscription = (row: SubscriptionRow) => {
    if (editingSubscription === row.user_id) {
      setEditingSubscription("");
      return;
    }
    void run(async () => {
      // Always start Edit from a fresh single-row DB read, not from a
      // possibly stale table row.
      const fresh = await getAdminSubscription(row.user_id);
      setSubs((current) =>
        current.map((item) => (item.user_id === fresh.user_id ? fresh : item)),
      );
      const form = subscriptionToForm(fresh);
      const suggested = suggestedMonthlyTotal(fresh);
      if (Number(fresh.monthly_total || 0) <= 0 && suggested > 0) {
        form.monthly_total = suggested;
      }
      setSubscriptionEdits((current) => ({
        ...current,
        [fresh.user_id]: form,
      }));
      setEditingSubscription(fresh.user_id);
    }, "Subscription loaded from DB ✓");
  };

  const addSubscription = () =>
    run(async () => {
      await createSubscription(newSubscription);
      setNewSubscription(blankSubscription);
      load();
    }, "Subscription created ✓ — visible on the customer dashboard now");

  const saveSubscription = (row: SubscriptionRow) =>
    run(async () => {
      const form = editedSubscription(row);
      const saved = await updateSubscription(row.user_id, {
        status: form.status,
        agent_limit: Math.trunc(form.agent_limit),
        channels: Math.trunc(form.channels),
        telephony_rented: form.telephony_rented,
        kb_extra_chars: Math.trunc(form.kb_extra_chars),
        kb_extra_faqs: Math.trunc(form.kb_extra_faqs),
        monthly_total: Number(form.monthly_total),
        renews_at: form.renews_at,
      });
      // Reflect the backend's saved DB row immediately; the full reload
      // below is only a refresh and must not be the sole proof of saving.
      setSubs((current) =>
        current.map((item) => (item.user_id === saved.user_id ? saved : item)),
      );
      setEditingSubscription("");
      setSubscriptionEdits((current) => {
        const next = { ...current };
        delete next[row.user_id];
        return next;
      });
      load();
    }, "Subscription saved ✓ — customer dashboard updated");

  const removeSubscription = (row: SubscriptionRow) => {
    if (
      !window.confirm(
        `Delete the subscription for ${row.user_name || row.user_email || row.user_id}? The customer dashboard will immediately show no active plan.`,
      )
    )
      return;
    void run(async () => {
      await deleteSubscription(row.user_id);
      if (editingSubscription === row.user_id) setEditingSubscription("");
      load();
    }, "Subscription deleted ✓");
  };

  const renderSubscriptionFields = (
    form: SubscriptionForm,
    update: (patch: Partial<SubscriptionForm>) => void,
    includeCustomer = false,
  ) => (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {includeCustomer && (
        <Field label="Customer">
          <select
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={form.user_id}
            onChange={(e) => update({ user_id: e.target.value })}
          >
            <option value="">Select customer…</option>
            {users
              .filter((user) => !subs.some((sub) => sub.user_id === user.id))
              .map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name || user.email}
                  {user.name && user.email ? ` · ${user.email}` : ""}
                </option>
              ))}
          </select>
        </Field>
      )}
      <Field label="Status">
        <select
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={form.status}
          onChange={(e) =>
            update({
              status: e.target.value as SubscriptionForm["status"],
            })
          }
        >
          <option value="active">Active</option>
          <option value="past_due">Past due</option>
          <option value="inactive">Inactive</option>
        </select>
      </Field>
      <Field label="Agent limit">
        <Input
          className="h-9 tabular-nums"
          type="number"
          min="0"
          value={form.agent_limit}
          onChange={(e) => update({ agent_limit: Number(e.target.value) })}
        />
      </Field>
      <Field
        label="Plan VoiceLink channels"
        hint="Total channels included in this subscription. Calls on a DID are still capped by that number's own channels."
      >
        <Input
          className="h-9 tabular-nums"
          type="number"
          min="1"
          max="1000"
          value={form.channels}
          onChange={(e) => update({ channels: Number(e.target.value) })}
        />
      </Field>
      <Field label="Monthly total ₹">
        <Input
          className="h-9 tabular-nums"
          type="number"
          min="0"
          step="0.01"
          value={form.monthly_total}
          onChange={(e) => update({ monthly_total: Number(e.target.value) })}
        />
      </Field>
      <Field label="Renews on">
        <Input
          className="h-9"
          type="date"
          value={form.renews_at}
          onChange={(e) => update({ renews_at: e.target.value })}
        />
      </Field>
      <Field label="Extra KB characters">
        <Input
          className="h-9 tabular-nums"
          type="number"
          min="0"
          value={form.kb_extra_chars}
          onChange={(e) => update({ kb_extra_chars: Number(e.target.value) })}
        />
      </Field>
      <Field label="Extra FAQs">
        <Input
          className="h-9 tabular-nums"
          type="number"
          min="0"
          value={form.kb_extra_faqs}
          onChange={(e) => update({ kb_extra_faqs: Number(e.target.value) })}
        />
      </Field>
      <div className="space-y-1.5">
        <Label className="text-xs font-medium text-muted-foreground">
          Telephony rented
        </Label>
        <label className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm shadow-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-primary"
            checked={form.telephony_rented}
            onChange={(e) => update({ telephony_rented: e.target.checked })}
          />
          Included
        </label>
      </div>
    </div>
  );

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
                  VoiceLink channels and telephony (₹ / month)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field
                    label="Extra VoiceLink channel ₹/month"
                    hint="The first channel is included when a customer buys a plan; each additional selected channel costs this per month."
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
            <CardContent className="space-y-5 pt-5">
              <div className="space-y-3 rounded-lg border border-dashed border-border p-4">
                <div>
                  <h3 className="text-sm font-semibold">
                    Add a customer subscription
                  </h3>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    Manual admin changes do not charge or refund the wallet
                    immediately. The monthly total below is what renewals
                    will charge, and saved values appear on the customer’s
                    Billing dashboard.
                  </p>
                </div>
                {renderSubscriptionFields(
                  newSubscription,
                  (patch) =>
                    setNewSubscription((current) => ({
                      ...current,
                      ...patch,
                    })),
                  true,
                )}
                <Button
                  size="sm"
                  disabled={busy || !newSubscription.user_id}
                  onClick={addSubscription}
                >
                  <Plus className="mr-2 h-3.5 w-3.5" />
                  Add subscription
                </Button>
              </div>

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
                        Channels
                      </th>
                      <th className="px-3 py-2 font-medium">Telephony</th>
                      <th className="px-3 py-2 text-right font-medium">
                        ₹/month
                      </th>
                      <th className="px-3 py-2 font-medium">Renews</th>
                      <th className="px-3 py-2 text-right font-medium">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {subs.map((subscription) => {
                      const effectiveChannels = Math.max(
                        1,
                        Number(subscription.channels || 0),
                        Number(subscription.plan_channels || 0),
                        Number(subscription.allocated_channels || 0),
                        Number(subscription.number_channels || 0),
                        Number(subscription.concurrency_lines || 0),
                      );
                      return (
                        <Fragment key={subscription.user_id}>
                          <tr className="border-b border-border/40">
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
                          <div className="font-medium">
                            {effectiveChannels}
                          </div>
                          <div className="whitespace-nowrap text-[10px] text-muted-foreground">
                            plan {subscription.plan_channels ?? 1} · provider{" "}
                            {subscription.allocated_channels ?? 0} · number{" "}
                            {subscription.number_channels ?? 0}
                          </div>
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
                        <td className="px-3 py-3">
                          <div className="flex justify-end gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={busy}
                              onClick={() =>
                                startEditSubscription(subscription)
                              }
                            >
                              <Pencil className="mr-1.5 h-3.5 w-3.5" />
                              Edit
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="text-destructive hover:text-destructive"
                              disabled={busy}
                              onClick={() => removeSubscription(subscription)}
                            >
                              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                              Delete
                            </Button>
                          </div>
                        </td>
                          </tr>
                          {editingSubscription === subscription.user_id && (
                            <tr className="border-b border-border/40 bg-muted/20">
                              <td colSpan={8} className="px-3 py-4">
                                <div className="space-y-3">
                                  <div>
                                    <h3 className="text-sm font-semibold">
                                      Edit subscription
                                    </h3>
                                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                                      These fields were loaded from this
                                      customer’s current subscription row in
                                      the DB. Saved values are read by the
                                      customer Billing dashboard on its next
                                      refresh. Editing plan channels does not
                                      change a DID’s own carrier channels; use
                                      Telephony for a manual number or the
                                      customer’s paid channel upgrade for a
                                      purchased number.
                                    </p>
                                    {Number(subscription.monthly_total || 0) <=
                                      0 &&
                                      Number(
                                        editedSubscription(subscription)
                                          .monthly_total || 0,
                                      ) > 0 && (
                                        <p className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
                                          The stored DB monthly total is ₹0.
                                          The amount in the form is prefilled
                                          from the matching agent/KB/channel
                                          prices in the DB. Review it before
                                          saving; Save will store it as the
                                          subscription’s monthly total.
                                        </p>
                                      )}
                                  </div>
                                  {renderSubscriptionFields(
                                    editedSubscription(subscription),
                                    (patch) =>
                                      setSubscriptionEdit(subscription, patch),
                                  )}
                                  {err && (
                                    <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
                                      Could not save: {err}
                                    </div>
                                  )}
                                  <div className="flex flex-wrap gap-2">
                                    <Button
                                      type="button"
                                      size="sm"
                                      disabled={busy}
                                      onClick={() =>
                                        saveSubscription(subscription)
                                      }
                                    >
                                      <Save className="mr-2 h-3.5 w-3.5" />
                                      {busy
                                        ? "Saving…"
                                        : "Save subscription"}
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      disabled={busy}
                                      onClick={() =>
                                        setEditingSubscription("")
                                      }
                                    >
                                      Cancel
                                    </Button>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}

                    {subs.length === 0 && (
                      <tr>
                        <td
                          colSpan={8}
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
