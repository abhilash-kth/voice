"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Loader2,
  Pause,
  Phone,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import {
  createManualTelephonyNumber,
  listUsers,
  type ApiUser,
  type ManualNumberBody,
  type TelephonyAccount,
  type TelephonyAccountDetail,
  type TelephonyNumber,
  type TelephonyOverview,
  type TelephonyPurchase,
} from "@/lib/api";
import { fmtDateTime, fmtINR, shortId } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function StatusBadge({ value }: { value: string }) {
  const good = ["active", "verified", "purchased", "assigned"].includes(value);
  const bad = ["failed", "needs_review", "suspended", "rejected"].includes(value);
  return (
    <Badge
      variant={good ? "default" : bad ? "destructive" : "secondary"}
      className="whitespace-nowrap capitalize"
    >
      {(value || "—").replace("_", " ")}
    </Badge>
  );
}

const headCls =
  "h-9 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground";
const cellCls = "px-3 py-2.5 align-top text-[13px]";
const wrapCls = `${cellCls} max-w-[240px] whitespace-normal break-words`;

function Owner({ name, email, id }: { name?: string; email?: string; id: string }) {
  return (
    <div className="min-w-[150px]">
      <p className="font-medium text-foreground">{name || email || shortId(id)}</p>
      {email && <p className="text-xs text-muted-foreground">{email}</p>}
      <p className="font-mono text-[10px] text-muted-foreground">{shortId(id)}</p>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <Card className="p-4 shadow-xs">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-2 text-2xl font-bold tabular-nums">{value}</div>
      {sub && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{sub}</p>}
    </Card>
  );
}

export function OverviewPanel({ overview }: { overview: TelephonyOverview }) {
  const activeNumbers = overview.counts.numbers_by_status.active || 0;
  const failedNumbers = overview.counts.numbers_by_status.failed || 0;
  const review = overview.counts.purchases_by_state.needs_review || 0;
  const verified = overview.counts.accounts_by_kyc.verified || 0;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Provider"
          value={overview.configured ? "Configured" : "Missing"}
          sub={overview.provider_error || overview.config.api_base_url}
        />
        <Stat
          label="Accounts / KYC verified"
          value={`${overview.counts.accounts} / ${verified}`}
          sub={`VoiceLink SIP ${overview.config.voicelink_sip}`}
        />
        <Stat
          label="Active numbers"
          value={`${activeNumbers} / ${overview.counts.numbers}`}
          sub={`${failedNumbers} failed · LiveKit SIP ${overview.config.livekit_sip}`}
        />
        <Stat
          label="Needs review"
          value={review}
          sub="Uncertain purchases must be reconciled; never replayed automatically."
        />
      </div>

      <Card className="p-4 shadow-xs">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
          <span>
            Settings source:{" "}
            <strong className="text-foreground">
              {overview.config.source === "super_admin"
                ? "Super Admin database"
                : "Env fallback"}
            </strong>
          </span>
          <span>
            Default trunk:{" "}
            <strong className="text-foreground">
              {overview.config.default_trunk_configured ? "configured" : "not set"}
            </strong>
          </span>
          <span>
            Tech prefix:{" "}
            <strong className="font-mono text-foreground">
              {overview.config.tech_prefix || "—"}
            </strong>
          </span>
          <span>
            Wallet bypass:{" "}
            <strong className="text-foreground">
              {overview.config.wallet_bypass ? "on" : "off"}
            </strong>
          </span>
          <span>
            Client KYC final-submit verified:{" "}
            <strong className="text-foreground">
              {overview.config.kyc_finalize_verified ? "yes" : "no (gated)"}
            </strong>
          </span>
          <span>
            KYC terms URL:{" "}
            <strong className="text-foreground">
              {overview.config.kyc_terms_configured ? "configured" : "missing"}
            </strong>
          </span>
        </div>
        {!overview.config.kyc_finalize_verified && (
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Final KYC submission remains gated until VoiceLink confirms the
            endpoint honours the per-customer client_id. SIP passwords are
            never shown here—only masked/configured state.
          </p>
        )}
      </Card>
    </div>
  );
}

export function AccountsTable({
  rows,
  busy,
  onDetail,
  onSync,
  onAllocate,
  onStatus,
}: {
  rows: TelephonyAccount[];
  busy: string;
  onDetail: (row: TelephonyAccount) => void;
  onSync: (row: TelephonyAccount) => void;
  onAllocate: (row: TelephonyAccount, amount: number) => void;
  onStatus: (row: TelephonyAccount, status: "active" | "suspended") => void;
}) {
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={headCls}>Customer</TableHead>
            <TableHead className={headCls}>VoiceLink account</TableHead>
            <TableHead className={headCls}>KYC</TableHead>
            <TableHead className={headCls}>Balance / channels</TableHead>
            <TableHead className={headCls}>Status</TableHead>
            <TableHead className={headCls}>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const loading = busy === r.id;
            return (
              <TableRow key={r.id}>
                <TableCell className={cellCls}>
                  <Owner name={r.user_name} email={r.user_email} id={r.user_id} />
                </TableCell>
                <TableCell className={wrapCls}>
                  <p className="font-medium">{r.name || "—"}</p>
                  <p className="text-xs text-muted-foreground">{r.email}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">
                    client {r.client_id} · {r.numbers_count ?? 0} numbers
                  </p>
                  {r.last_error && (
                    <p className="mt-1 text-xs text-destructive">{r.last_error}</p>
                  )}
                </TableCell>
                <TableCell className={cellCls}>
                  <StatusBadge value={r.kyc_status} />
                  <p className="mt-1 text-xs capitalize text-muted-foreground">
                    step: {r.kyc_step.replace("_", " ")}
                  </p>
                </TableCell>
                <TableCell className={cellCls}>
                  <p className="font-semibold tabular-nums">{fmtINR(r.wallet_balance)}</p>
                  <p className="text-xs text-muted-foreground">
                    {r.channels_allocated} allocated · {r.channels_available} available
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    synced {fmtDateTime(r.last_synced_at)}
                  </p>
                </TableCell>
                <TableCell className={cellCls}>
                  <StatusBadge value={r.status} />
                </TableCell>
                <TableCell className={`${cellCls} min-w-[300px] whitespace-normal`}>
                  <div className="flex flex-wrap gap-1.5">
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => onDetail(r)}>
                      <Eye className="h-3.5 w-3.5" /> Detail
                    </Button>
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => onSync(r)}>
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                      Sync
                    </Button>
                    <Button
                      size="sm"
                      variant={r.status === "suspended" ? "default" : "destructive"}
                      disabled={loading}
                      onClick={() => onStatus(r, r.status === "suspended" ? "active" : "suspended")}
                    >
                      {r.status === "suspended" ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
                      {r.status === "suspended" ? "Activate" : "Suspend"}
                    </Button>
                  </div>
                  <div className="mt-2 flex max-w-[260px] gap-1.5">
                    <Input
                      type="number"
                      min={1}
                      placeholder="₹ provider funds"
                      value={amounts[r.id] || ""}
                      disabled={loading}
                      onChange={(e) => setAmounts({ ...amounts, [r.id]: e.target.value })}
                      className="h-8"
                    />
                    <Button
                      size="sm"
                      disabled={loading || Number(amounts[r.id]) <= 0}
                      onClick={() => onAllocate(r, Number(amounts[r.id]))}
                    >
                      <Wallet className="h-3.5 w-3.5" /> Allocate
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export function AccountDetailPanel({
  detail,
  onClose,
}: {
  detail: TelephonyAccountDetail;
  onClose: () => void;
}) {
  const a = detail.account;
  const docs = (a.kyc_meta?.documents || {}) as Record<
    string,
    { verified?: boolean; uploaded?: boolean }
  >;
  return (
    <Card className="space-y-4 border-primary/25 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold">
            <ShieldCheck className="h-4 w-4 text-primary" /> Account detail
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {a.user_name || a.user_email || a.name} · provider client {a.client_id}
          </p>
        </div>
        <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close detail">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="grid gap-3 text-sm sm:grid-cols-4">
        <p>Status<br /><StatusBadge value={a.status} /></p>
        <p>KYC<br /><StatusBadge value={a.kyc_status} /></p>
        <p>Calling balance<br /><strong>{fmtINR(a.wallet_balance)}</strong></p>
        <p>Channels<br /><strong>{a.channels_allocated}</strong> allocated</p>
      </div>
      {Object.keys(docs).length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {Object.entries(docs).map(([name, d]) => (
            <span key={name} className="rounded-full border px-2.5 py-1 capitalize">
              {name}: {d.verified ? "verified" : "not verified"} · {d.uploaded ? "uploaded" : "not uploaded"}
            </span>
          ))}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="text-sm font-semibold">Numbers ({detail.numbers.length})</h4>
          <ul className="mt-2 space-y-1 text-sm">
            {detail.numbers.map((n) => (
              <li key={n.id} className="flex justify-between gap-2 rounded bg-muted/40 px-2 py-1.5">
                <span className="font-mono">{n.number}</span>
                <StatusBadge value={n.status} />
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-semibold">Purchases ({detail.purchases.length})</h4>
          <ul className="mt-2 space-y-1 text-sm">
            {detail.purchases.map((p) => (
              <li key={p.id} className="flex justify-between gap-2 rounded bg-muted/40 px-2 py-1.5">
                <span className="font-mono">{p.number || shortId(p.id)}</span>
                <StatusBadge value={p.state} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

export function NumbersTable({
  rows,
  busy,
  onRetry,
  onSync,
  onStatus,
}: {
  rows: TelephonyNumber[];
  busy: string;
  onRetry: (row: TelephonyNumber) => void;
  onSync: (row: TelephonyNumber) => void;
  onStatus: (row: TelephonyNumber, status: "active" | "suspended") => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={headCls}>Number / owner</TableHead>
            <TableHead className={headCls}>Activation</TableHead>
            <TableHead className={headCls}>Trunks (masked secret)</TableHead>
            <TableHead className={headCls}>Agents</TableHead>
            <TableHead className={headCls}>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const loading = busy === r.id;
            return (
              <TableRow key={r.id}>
                <TableCell className={wrapCls}>
                  <p className="font-mono text-sm font-bold">{r.number}</p>
                  <Owner name={r.user_name} email={r.user_email} id={r.user_id} />
                  <p className="text-xs text-muted-foreground">
                    {r.channels} ch · {fmtINR(r.monthly_rate)}/mo · expires {fmtDateTime(r.expires_at)}
                  </p>
                </TableCell>
                <TableCell className={wrapCls}>
                  <StatusBadge value={r.status} />
                  <p className="mt-1 text-xs text-muted-foreground">
                    step: {(r.provisioning_step || "—").replace("_", " ")} · {r.source}
                  </p>
                  {r.last_error && <p className="mt-1 text-xs text-destructive">{r.last_error}</p>}
                </TableCell>
                <TableCell className={`${wrapCls} font-mono text-[11px]`}>
                  <p>SIP user: {r.sip_username || "—"}</p>
                  <p>Password: {r.has_sip_password ? r.sip_password_masked || "configured" : "not configured"}</p>
                  <p>VL trunk: {r.voice_link_trunk_id || "—"} · route {r.voice_link_routing_id || "—"}</p>
                  <p>LK out: {r.livekit_outbound_trunk_id || "—"}</p>
                  <p>LK in: {r.livekit_inbound_trunk_id || "—"} · rule {r.livekit_dispatch_rule_id || "—"}</p>
                  <p>Prefix: {r.dial_prefix || "—"}</p>
                </TableCell>
                <TableCell className={wrapCls}>
                  {(r.agents || []).length === 0 ? (
                    <span className="text-muted-foreground">Unassigned</span>
                  ) : (
                    <ul className="space-y-1">
                      {(r.agents || []).map((a) => (
                        <li key={a.id}>
                          <span className="font-medium">{a.name}</span>{" "}
                          <span className="text-xs capitalize text-muted-foreground">
                            {a.purpose}{a.enabled ? "" : " · disabled"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </TableCell>
                <TableCell className={`${cellCls} min-w-[230px] whitespace-normal`}>
                  <div className="flex flex-wrap gap-1.5">
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => onRetry(r)}>
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                      Retry
                    </Button>
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => onSync(r)}>
                      Sync inbound
                    </Button>
                    <Button
                      size="sm"
                      variant={r.status === "suspended" ? "default" : "destructive"}
                      disabled={loading}
                      onClick={() => onStatus(r, r.status === "suspended" ? "active" : "suspended")}
                    >
                      {r.status === "suspended" ? "Activate" : "Suspend"}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export function PurchasesTable({ rows }: { rows: TelephonyPurchase[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={headCls}>Number / owner</TableHead>
            <TableHead className={headCls}>State</TableHead>
            <TableHead className={headCls}>Money</TableHead>
            <TableHead className={headCls}>Provider refs</TableHead>
            <TableHead className={headCls}>Updated / error</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id}>
              <TableCell className={wrapCls}>
                <p className="font-mono font-semibold">{r.number || "—"}</p>
                <Owner name={r.user_name} email={r.user_email} id={r.user_id} />
              </TableCell>
              <TableCell className={cellCls}>
                <StatusBadge value={r.state} />
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.months} mo · {r.channels} ch
                </p>
              </TableCell>
              <TableCell className={cellCls}>
                <p>Quote {fmtINR(r.quote_total)}</p>
                <p>Charged {fmtINR(r.customer_charge)}</p>
                <p className="text-xs text-muted-foreground">Monthly {fmtINR(r.monthly_rate)}</p>
              </TableCell>
              <TableCell className={`${wrapCls} font-mono text-[11px]`}>
                order {r.provider_order_id || "—"}<br />
                purchase {r.provider_purchase_id || "—"}<br />
                DID {r.provider_did_id || "—"}
              </TableCell>
              <TableCell className={wrapCls}>
                {fmtDateTime(r.updated_at)}
                {r.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function ManualNumberForm({
  onCreated,
}: {
  onCreated: (number: TelephonyNumber) => void;
}) {
  const [users, setUsers] = useState<ApiUser[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<ManualNumberBody>({
    user_id: "",
    number: "",
    livekit_outbound_trunk_id: "",
    livekit_inbound_trunk_id: "",
    dial_prefix: "",
    channels: 1,
    expires_at: "",
  });

  useEffect(() => {
    listUsers({ page_size: 100 })
      .then((out) => setUsers(out.items))
      .catch(() => setUsers([]));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await createManualTelephonyNumber({
        ...form,
        channels: Number(form.channels || 1),
      });
      onCreated(out);
      setForm({ ...form, number: "" });
    } catch (err) {
      setError((err as Error).message || "Manual number could not be registered.");
    } finally {
      setBusy(false);
    }
  };

  const field = (
    label: string,
    key: keyof ManualNumberBody,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Input
        value={String(form[key] ?? "")}
        disabled={busy}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        {...props}
      />
    </div>
  );

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-border/60 bg-card p-5 shadow-sm">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Phone className="h-4 w-4 text-primary" /> Register an existing DID
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          For an already-provisioned number such as the original single-tenant
          line. Enter LiveKit trunk IDs only—never a SIP password.
        </p>
      </div>
      {error && (
        <p className="flex gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs">Customer</Label>
          {users.length > 0 ? (
            <select
              required
              value={form.user_id}
              disabled={busy}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">Select customer…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name || u.email} ({u.email})
                </option>
              ))}
            </select>
          ) : (
            <Input
              required
              placeholder="Customer user ID"
              value={form.user_id}
              disabled={busy}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}
            />
          )}
        </div>
        {field("Phone number (E.164)", "number", { required: true, placeholder: "+91XXXXXXXXXX" })}
        {field("LiveKit outbound trunk ID", "livekit_outbound_trunk_id", { placeholder: "ST_…" })}
        {field("LiveKit inbound trunk ID", "livekit_inbound_trunk_id", { placeholder: "ST_…" })}
        {field("Carrier tech prefix", "dial_prefix", { placeholder: "45454" })}
        {field("Channels", "channels", { type: "number", min: 1, max: 100 })}
        {field("Expiry (ISO date, optional)", "expires_at", { placeholder: "2026-10-31" })}
      </div>
      <Button type="submit" disabled={busy}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Register number
      </Button>
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
        The customer can then assign it to an agent; provider secrets stay server-side.
      </p>
    </form>
  );
}
