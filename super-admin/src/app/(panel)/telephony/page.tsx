"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShoppingCart,
  Users,
} from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Pager from "@/components/Pager";
import { StateBox } from "@/components/StateBox";
import {
  allocateTelephonyWallet,
  getTelephonyAccount,
  getTelephonyOverview,
  getTelephonySettings,
  listTelephonyAccounts,
  listTelephonyNumbers,
  listTelephonyPurchases,
  retryTelephonyNumber,
  setTelephonyAccountStatus,
  setTelephonyNumberStatus,
  syncTelephonyAccount,
  syncTelephonyInbound,
  type Paged,
  type TelephonyAccount,
  type TelephonyAccountDetail,
  type TelephonyNumber,
  type TelephonyOverview,
  type TelephonyPurchase,
  type TelephonySettings,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  AccountDetailPanel,
  AccountsTable,
  ManualNumberForm,
  NumbersTable,
  OverviewPanel,
  PurchasesTable,
} from "./components";
import { TelephonySettingsForm } from "./settings";

type Tab = "settings" | "accounts" | "numbers" | "purchases" | "manual";

const PAGE_SIZE = 25;
const emptyPage = { items: [], total: 0, page: 1, page_size: PAGE_SIZE };

const STATUS_OPTIONS: Record<Exclude<Tab, "manual" | "settings">, string[]> = {
  accounts: ["active", "suspended"],
  numbers: ["provisioning", "active", "failed", "suspended"],
  purchases: [
    "draft",
    "quoted",
    "confirming",
    "purchased",
    "assigned",
    "provisioning",
    "active",
    "needs_review",
    "failed",
    "refunded",
  ],
};

export default function TelephonyPage() {
  const [tab, setTab] = useState<Tab>("accounts");
  const [overview, setOverview] = useState<TelephonyOverview | null>(null);
  const [telephonySettings, setTelephonySettings] =
    useState<TelephonySettings | null>(null);
  const [accounts, setAccounts] =
    useState<Paged<TelephonyAccount>>(emptyPage);
  const [numbers, setNumbers] = useState<Paged<TelephonyNumber>>(emptyPage);
  const [purchases, setPurchases] =
    useState<Paged<TelephonyPurchase>>(emptyPage);
  const [detail, setDetail] = useState<TelephonyAccountDetail | null>(null);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [kycStatus, setKycStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<{
    kind: "ok" | "error";
    text: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const jobs: Promise<unknown>[] = [
        getTelephonyOverview().then(setOverview),
      ];
      if (tab === "settings") {
        jobs.push(
          getTelephonySettings().then((out) => setTelephonySettings(out.settings)),
        );
      } else if (tab === "accounts") {
        jobs.push(
          listTelephonyAccounts({
            page,
            page_size: PAGE_SIZE,
            q: query,
            status,
            kyc_status: kycStatus,
          }).then(setAccounts),
        );
      } else if (tab === "numbers") {
        jobs.push(
          listTelephonyNumbers({
            page,
            page_size: PAGE_SIZE,
            q: query,
            status,
          }).then(setNumbers),
        );
      } else if (tab === "purchases") {
        jobs.push(
          listTelephonyPurchases({
            page,
            page_size: PAGE_SIZE,
            state: status,
          }).then(setPurchases),
        );
      }
      await Promise.all(jobs);
      setError("");
    } catch (e) {
      setError((e as Error).message || "Could not load telephony data.");
    } finally {
      setLoading(false);
    }
  }, [kycStatus, page, query, status, tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const switchTab = (next: Tab) => {
    setTab(next);
    setPage(1);
    setStatus("");
    setDetail(null);
  };

  const run = async (
    id: string,
    success: string,
    fn: () => Promise<unknown>,
  ) => {
    if (busy) return;
    setBusy(id);
    setNotice(null);
    try {
      await fn();
      setNotice({ kind: "ok", text: success });
      await load();
    } catch (e) {
      setNotice({
        kind: "error",
        text: (e as Error).message || "Telephony action failed.",
      });
      await load();
    } finally {
      setBusy("");
    }
  };

  const activePage =
    tab === "accounts"
      ? accounts
      : tab === "numbers"
        ? numbers
        : tab === "purchases"
          ? purchases
          : emptyPage;
  const empty =
    tab !== "manual" && tab !== "settings" && activePage.items.length === 0
      ? "No matching telephony records yet."
      : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Telephony"
        subtitle="Manage customer VoiceLink accounts, KYC, purchased numbers, activation, trunks and purchases. SIP passwords are masked and never displayed."
      >
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9"
          disabled={loading}
          onClick={() => void load()}
        >
          <RefreshCw className={cn("mr-2 h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </PageHeader>

      {notice && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-lg border p-3 text-sm",
            notice.kind === "ok"
              ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
              : "border-destructive/25 bg-destructive/10 text-destructive",
          )}
          role="status"
        >
          {notice.kind === "ok" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          {notice.text}
        </div>
      )}

      {overview && <OverviewPanel overview={overview} />}

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1 rounded-lg bg-muted/50 p-1">
          {(
            [
              ["settings", "Settings", Settings],
              ["accounts", "Accounts", Users],
              ["numbers", "Numbers", Phone],
              ["purchases", "Purchases", ShoppingCart],
              ["manual", "Manual number", Plus],
            ] as const
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              onClick={() => switchTab(value)}
              className={cn(
                "inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium",
                tab === value
                  ? "bg-background shadow-sm ring-1 ring-border"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </div>

        {tab !== "manual" && tab !== "settings" && (
          <div className="flex flex-wrap gap-2">
            {tab !== "purchases" && (
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                  placeholder={tab === "accounts" ? "Search customer/client…" : "Search number/customer/trunk…"}
                  className="h-9 w-64 pl-8"
                />
              </div>
            )}
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm capitalize"
              aria-label="Status filter"
            >
              <option value="">All {tab === "purchases" ? "states" : "statuses"}</option>
              {STATUS_OPTIONS[tab].map((s) => (
                <option key={s} value={s}>
                  {s.replace("_", " ")}
                </option>
              ))}
            </select>
            {tab === "accounts" && (
              <select
                value={kycStatus}
                onChange={(e) => {
                  setKycStatus(e.target.value);
                  setPage(1);
                }}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm capitalize"
                aria-label="KYC filter"
              >
                <option value="">All KYC</option>
                {["not_started", "in_progress", "pending", "submitted", "verified", "rejected"].map((s) => (
                  <option key={s} value={s}>
                    {s.replace("_", " ")}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      <StateBox loading={loading && !overview} error={error || null} empty={empty}>
        {tab === "settings" ? (
          telephonySettings ? (
            <TelephonySettingsForm
              initial={telephonySettings}
              onSaved={(settings) => {
                setTelephonySettings(settings);
                void getTelephonyOverview()
                  .then(setOverview)
                  .catch(() => undefined);
              }}
            />
          ) : (
            <div className="rounded-xl border border-border/60 bg-card p-5 text-sm text-muted-foreground">
              Loading telephony settings…
            </div>
          )
        ) : tab === "manual" ? (
          <ManualNumberForm
            onCreated={(number) => {
              setNotice({
                kind: "ok",
                text: `Manual number ${number.number} registered.`,
              });
              switchTab("numbers");
            }}
          />
        ) : tab === "accounts" ? (
          <div className="space-y-4">
            {detail && (
              <AccountDetailPanel detail={detail} onClose={() => setDetail(null)} />
            )}
            <AccountsTable
              rows={accounts.items}
              busy={busy}
              onDetail={(row) =>
                void run(row.id, "Account detail loaded.", async () => {
                  setDetail(await getTelephonyAccount(row.id));
                })
              }
              onSync={(row) =>
                void run(row.id, "Account and provider numbers synced.", async () => {
                  setDetail(await syncTelephonyAccount(row.id));
                })
              }
              onAllocate={(row, amount) => {
                if (
                  window.confirm(
                    `Allocate ₹${amount.toFixed(2)} of provider calling funds to ${row.user_email || row.email}? This does not charge the customer's app wallet.`,
                  )
                ) {
                  void run(row.id, "Provider calling balance allocated.", () =>
                    allocateTelephonyWallet(row.id, amount),
                  );
                }
              }}
              onStatus={(row, next) => {
                if (
                  next === "active" ||
                  window.confirm(
                    "Suspend this telephony account? Inbound routing will be removed and assigned outbound calls blocked.",
                  )
                ) {
                  void run(row.id, `Account ${next}.`, () =>
                    setTelephonyAccountStatus(row.id, next),
                  );
                }
              }}
            />
            <Pager total={accounts.total} page={page} pageSize={PAGE_SIZE} onPage={setPage} />
          </div>
        ) : tab === "numbers" ? (
          <div className="space-y-4">
            <NumbersTable
              rows={numbers.items}
              busy={busy}
              onRetry={(row) =>
                void run(row.id, "Activation retry completed.", () =>
                  retryTelephonyNumber(row.id),
                )
              }
              onSync={(row) =>
                void run(row.id, "Inbound routing synced.", () =>
                  syncTelephonyInbound(row.id),
                )
              }
              onStatus={(row, next) => {
                if (
                  next === "active" ||
                  window.confirm(
                    `Suspend ${row.number}? Assigned agents will no longer be able to use it.`,
                  )
                ) {
                  void run(row.id, `Number ${next}.`, () =>
                    setTelephonyNumberStatus(row.id, next),
                  );
                }
              }}
            />
            <Pager total={numbers.total} page={page} pageSize={PAGE_SIZE} onPage={setPage} />
          </div>
        ) : (
          <div className="space-y-4">
            <PurchasesTable rows={purchases.items} />
            <Pager total={purchases.total} page={page} pageSize={PAGE_SIZE} onPage={setPage} />
          </div>
        )}
      </StateBox>
    </div>
  );
}
