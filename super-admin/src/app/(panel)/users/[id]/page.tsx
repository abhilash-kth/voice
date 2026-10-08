"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  UserX,
  UserCheck,
  Wallet,
  Activity,
  CheckCircle2,
  XCircle,
  IndianRupee,
  Clock,
  Database,
  ArrowUpRight,
  ArrowDownRight,
  Info,
  Mail,
  Shield,
  ShieldOff,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useBusy } from "@/components/PageHeader";
import { StateBox } from "@/components/StateBox";
import {
  getUserDetail,
  setUserRole,
  setUserDisabled,
  adjustWallet,
  type UserDetail,
} from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtINR } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

export default function UserDetailPage() {
  const params = useParams();
  const router = useRouter();
  const userId = String(params.id ?? "");

  const { busy, msg, err, run } = useBusy();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const {
    data: detail,
    isPending: loading,
    error,
    refetch,
  } = useQuery<UserDetail, Error>({
    queryKey: ["userDetail", userId],
    queryFn: () => getUserDetail(userId),
    enabled: Boolean(userId),
  });

  const act = (fn: () => Promise<unknown>, okMsg: string) =>
    run(async () => {
      await fn();
      await refetch();
    }, okMsg);

  const email = detail?.user.email ?? "Loading profile…";
  const name = detail?.user.name || email;
  const isAdmin = detail?.user.role === "SUPER_ADMIN";
  const isDisabled = detail?.user.disabled ?? false;
  const usage = detail?.usage;

  const initials = (detail?.user.name || detail?.user.email || "U")
    .split(/[\s@]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");

  return (
    <div className="flex min-h-full flex-col pb-12">
      {/* Identity Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => router.push("/users")}
            aria-label="Back to users"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>

          <Avatar className="h-11 w-11 shrink-0 rounded-full border border-border/50 bg-muted">
            <AvatarFallback className="rounded-full bg-muted text-sm font-semibold text-foreground">
              {initials || "U"}
            </AvatarFallback>
          </Avatar>

          <div className="flex flex-col justify-center">
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold tracking-tight text-foreground">
                {name}
              </h1>
              {detail && (
                <>
                  {isAdmin ? (
                    <Badge
                      variant="outline"
                      className="h-5 border-amber-500/25 bg-amber-500/10 px-1.5 font-mono text-[10px] font-semibold text-amber-700 dark:text-amber-400"
                    >
                      SUPER_ADMIN
                    </Badge>
                  ) : (
                    <Badge
                      variant="outline"
                      className="h-5 border-border/60 bg-muted/40 px-1.5 font-mono text-[10px] font-semibold text-muted-foreground"
                    >
                      USER
                    </Badge>
                  )}
                  {isDisabled ? (
                    <Badge
                      variant="outline"
                      className="h-5 gap-1 border-rose-500/25 bg-rose-500/10 px-1.5 text-[10px] font-semibold text-rose-600 dark:text-rose-400"
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                      Disabled
                    </Badge>
                  ) : (
                    <Badge
                      variant="outline"
                      className="h-5 gap-1 border-emerald-500/25 bg-emerald-500/10 px-1.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400"
                    >
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      </span>
                      Active
                    </Badge>
                  )}
                </>
              )}
            </div>

            <div className="mt-0.5 flex items-center gap-3 text-[13px] text-muted-foreground">
              {detail?.user.name && (
                <span className="inline-flex items-center gap-1.5">
                  <Mail className="h-3.5 w-3.5" />
                  {email}
                </span>
              )}
              {detail && (
                <span className="inline-flex items-center gap-1.5">
                  <span className="text-muted-foreground/60">Joined</span>
                  <span className="tabular-nums">
                    {fmtDateTime(detail.user.created_at)}
                  </span>
                </span>
              )}
            </div>
          </div>
        </div>

        {(msg || err) && (
          <div
            className={`mt-4 flex items-center gap-2.5 rounded-md border px-3 py-2.5 text-sm font-medium ${
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
      </div>

      <StateBox
        loading={loading}
        error={error?.message}
        empty={!userId ? "Missing user ID." : null}
      >
        {detail && (
          <div className="space-y-4">
            {/* ROW 1: KPI STRIP */}
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Card className="relative overflow-hidden border-0 bg-primary py-0 text-primary-foreground shadow-sm">
                <div
                  className="pointer-events-none absolute inset-0 opacity-[0.15]"
                  style={{
                    backgroundImage:
                      "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
                    backgroundSize: "12px 12px",
                  }}
                />
                <div className="relative p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-primary-foreground/80">
                      Wallet Balance
                    </p>
                    <Wallet className="h-4 w-4 opacity-80" />
                  </div>
                  <p className="mt-2.5 text-2xl font-bold tracking-tight tabular-nums">
                    {fmtINR(detail.user.wallet_balance)}
                  </p>
                </div>
              </Card>

              {usage && (
                <>
                  <Card className="border-border/60 py-0 shadow-sm">
                    <div className="p-4">
                      <div className="flex items-center justify-between">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Total Calls
                        </p>
                        <Activity className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                      </div>
                      <p className="mt-2.5 text-2xl font-bold tracking-tight tabular-nums text-foreground">
                        {usage.totalCallsCount}
                      </p>
                    </div>
                  </Card>

                  <Card className="border-border/60 py-0 shadow-sm">
                    <div className="p-4">
                      <div className="flex items-center justify-between">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Talk Time
                        </p>
                        <Clock className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                      </div>
                      <p className="mt-2.5 text-2xl font-bold tracking-tight tabular-nums text-foreground">
                        {fmtDuration(usage.totalMinutesUsed * 60)}
                      </p>
                    </div>
                  </Card>

                  <Card className="border-border/60 py-0 shadow-sm">
                    <div className="p-4">
                      <div className="flex items-center justify-between">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Tokens (In/Out)
                        </p>
                        <Database className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                      </div>
                      <p className="mt-2.5 flex items-baseline gap-1 text-2xl font-bold tracking-tight tabular-nums text-foreground">
                        {usage.llmInputTokens}
                        <span className="text-sm font-normal text-muted-foreground/50">
                          /
                        </span>
                        {usage.llmOutputTokens}
                      </p>
                    </div>
                  </Card>
                </>
              )}
            </div>

            {/* ROW 2: Management Blocks */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="flex flex-col border-border/60 py-0 shadow-sm">
                <div className="border-b border-border/60 bg-muted/20 px-4 py-3">
                  <h3 className="text-sm font-semibold">Access Control</h3>
                </div>
                <div className="flex flex-1 flex-col justify-between p-4">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                            isAdmin
                              ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {isAdmin ? (
                            <Shield className="h-4 w-4" />
                          ) : (
                            <ShieldOff className="h-4 w-4" />
                          )}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">
                            {isAdmin ? "Super Admin" : "Standard User"}
                          </p>
                          <p className="truncate text-[11px] text-muted-foreground">
                            {isAdmin
                              ? "Full platform control."
                              : "Workspace access only."}
                          </p>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        className="h-8 shrink-0 text-xs"
                        onClick={() => {
                          if (
                            window.confirm(
                              isAdmin
                                ? `Demote ${email} to USER?`
                                : `Promote ${email} to SUPER_ADMIN? They get full platform control.`,
                            )
                          ) {
                            act(
                              () =>
                                setUserRole(
                                  userId,
                                  isAdmin ? "USER" : "SUPER_ADMIN",
                                ),
                              "Role updated ✓",
                            );
                          }
                        }}
                      >
                        {isAdmin ? "Demote" : "Promote"}
                      </Button>
                    </div>

                    <div className="h-px w-full bg-border/60" />

                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                            isDisabled
                              ? "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                              : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                          }`}
                        >
                          {isDisabled ? (
                            <UserX className="h-4 w-4" />
                          ) : (
                            <UserCheck className="h-4 w-4" />
                          )}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">
                            {isDisabled ? "Suspended" : "Active"}
                          </p>
                          <p className="truncate text-[11px] text-muted-foreground">
                            {isDisabled
                              ? "Blocked from API."
                              : "Can authenticate."}
                          </p>
                        </div>
                      </div>
                      <Button
                        variant={isDisabled ? "outline" : "destructive"}
                        size="sm"
                        disabled={busy}
                        className="h-8 shrink-0 text-xs"
                        onClick={() => {
                          if (
                            window.confirm(
                              isDisabled
                                ? `Enable ${email}?`
                                : `Disable ${email}? They will be logged out and blocked from the API.`,
                            )
                          ) {
                            act(
                              () => setUserDisabled(userId, !isDisabled),
                              isDisabled ? "User enabled ✓" : "User disabled ✓",
                            );
                          }
                        }}
                      >
                        {isDisabled ? "Restore access" : "Suspend"}
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>

              <Card className="flex flex-col border-border/60 py-0 shadow-sm">
                <div className="border-b border-border/60 bg-muted/20 px-4 py-3">
                  <h3 className="text-sm font-semibold">Adjust Wallet</h3>
                </div>
                <div className="flex flex-1 flex-col p-4">
                  <div className="flex gap-3">
                    <div className="w-1/3 space-y-1.5">
                      <Label className="text-xs font-medium text-muted-foreground">
                        Amount
                      </Label>
                      <div className="relative">
                        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs font-medium text-muted-foreground">
                          ₹
                        </span>
                        <Input
                          className={`h-8 pl-6 text-sm tabular-nums focus-visible:ring-1 ${
                            amount && !isNaN(Number(amount))
                              ? Number(amount) >= 0
                                ? "focus-visible:ring-emerald-500"
                                : "focus-visible:ring-rose-500"
                              : ""
                          }`}
                          type="number"
                          step="0.01"
                          placeholder="0.00"
                          value={amount}
                          onChange={(e) => setAmount(e.target.value)}
                        />
                      </div>
                    </div>

                    <div className="flex-1 space-y-1.5">
                      <Label className="text-xs font-medium text-muted-foreground">
                        Note{" "}
                        <span className="font-normal opacity-70">(req)</span>
                      </Label>
                      <Input
                        className="h-8 text-sm"
                        placeholder="Reason…"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="mt-auto flex items-center justify-between pt-4">
                    <div className="flex items-center gap-1.5 text-[11px] font-medium">
                      {amount && !isNaN(Number(amount)) ? (
                        Number(amount) >= 0 ? (
                          <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                            <ArrowUpRight className="h-3.5 w-3.5" />
                            Adds credit
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-rose-600 dark:text-rose-400">
                            <ArrowDownRight className="h-3.5 w-3.5" />
                            Deducts balance
                          </span>
                        )
                      ) : (
                        <span className="flex items-center gap-1 text-muted-foreground">
                          <Info className="h-3.5 w-3.5" />
                          +/- amounts supported
                        </span>
                      )}
                    </div>

                    <Button
                      className={`h-8 text-xs ${
                        amount && !isNaN(Number(amount)) && Number(amount) < 0
                          ? "bg-rose-600 hover:bg-rose-700 text-white"
                          : "bg-emerald-600 hover:bg-emerald-700 text-white"
                      }`}
                      disabled={busy || !amount || !note.trim()}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Adjust ${email}'s wallet by ₹${amount}?`,
                          )
                        ) {
                          act(async () => {
                            await adjustWallet(
                              userId,
                              Number(amount),
                              note.trim(),
                            );
                            setAmount("");
                            setNote("");
                          }, "Wallet adjusted ✓");
                        }
                      }}
                    >
                      <IndianRupee className="mr-1 h-3 w-3" />
                      Apply
                    </Button>
                  </div>
                </div>
              </Card>
            </div>

            {/* ROW 3: Transaction Ledger */}
            {detail.wallet.transactions.length > 0 && (
              <Card className="border-border/60 py-0 shadow-sm">
                <div className="border-b border-border/60 bg-muted/20 px-4 py-3">
                  <h3 className="text-sm font-semibold">Transaction Ledger</h3>
                </div>
                <Table>
                  <TableHeader>
                    <TableRow className="border-b border-border/60 bg-muted/30 hover:bg-muted/30">
                      <TableHead className="w-[180px] h-9 px-4 py-2 text-xs font-medium text-muted-foreground">
                        Date
                      </TableHead>
                      <TableHead className="h-9 py-2 text-xs font-medium text-muted-foreground">
                        Description
                      </TableHead>
                      <TableHead className="h-9 px-4 py-2 text-right text-xs font-medium text-muted-foreground">
                        Amount
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.wallet.transactions.slice(0, 15).map((t, i) => {
                      const tx = t as Record<string, unknown>;
                      const txAmount = Number(tx.amount ?? 0);
                      const isCredit = txAmount >= 0;

                      return (
                        <TableRow
                          key={i}
                          className="border-b border-border/40 transition-colors hover:bg-muted/10"
                        >
                          <TableCell className="whitespace-nowrap px-4 py-2.5 text-[11px] tabular-nums text-muted-foreground">
                            {fmtDateTime(String(tx.ts ?? ""))}
                          </TableCell>
                          <TableCell className="py-2.5 text-xs text-foreground">
                            <div className="flex items-center gap-2">
                              {isCredit ? (
                                <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                              ) : (
                                <ArrowDownRight className="h-3.5 w-3.5 shrink-0 text-rose-600 dark:text-rose-400" />
                              )}
                              <span className="truncate">
                                {String(tx.note ?? "Wallet adjustment")}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="px-4 py-2.5 text-right">
                            <span
                              className={`text-xs font-medium tabular-nums ${
                                isCredit
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : "text-rose-600 dark:text-rose-400"
                              }`}
                            >
                              {isCredit ? "+" : ""}
                              {fmtINR(txAmount)}
                            </span>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </Card>
            )}
          </div>
        )}
      </StateBox>
    </div>
  );
}
