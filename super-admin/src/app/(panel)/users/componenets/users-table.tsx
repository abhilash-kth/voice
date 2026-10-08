"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Search, Shield, Eye, Wallet, Users as UsersIcon } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Pager from "@/components/Pager";
import { listUsers, type ApiUser, type Paged } from "@/lib/api";
import { fmtDateTime, fmtINR } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { StateBox } from "@/components/StateBox";
import { useQuery, keepPreviousData } from "@tanstack/react-query";

function parsePage(v: string | null) {
  const n = Number(v || "1");
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
}

export default function UsersTable() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // URL is the source of truth for list state
  const q = searchParams.get("q") || "";
  const role = searchParams.get("role") || "";
  const status = searchParams.get("status") || "";
  const pageL = parsePage(searchParams.get("page"));

  // Local draft for search input so typing doesn't thrash the URL every keystroke
  const [qDraft, setQDraft] = useState(q);
  useEffect(() => {
    setQDraft(q);
  }, [q]);

  const setParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(patch).forEach(([key, value]) => {
        if (value === null || value === undefined || value === "") {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  // query function for fetch the user data as per the page size
  const {
    data,
    isPending: loading,
    error,
    refetch: refetchUsers,
  } = useQuery<Paged<ApiUser>, Error>({
    queryKey: ["users", { page: pageL, q, role, status }],
    queryFn: () =>
      listUsers({
        page: pageL,
        page_size: 25,
        q: q || undefined,
        role: role || undefined,
        disabled: status === "" ? undefined : status === "disabled",
      }),
    placeholderData: keepPreviousData,
  });

  // Debounce search → URL
  useEffect(() => {
    const t = setTimeout(() => {
      if (qDraft === q) return;
      setParams({ q: qDraft || null, page: "1" });
    }, 300);
    return () => clearTimeout(t);
  }, [qDraft, q, setParams]);

  const getInitials = (name?: string, email?: string) => {
    return (name || email || "U")
      .split(/[\s@]/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase())
      .join("");
  };

  return (
    <div className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden pb-2">
      {/* Fixed Header & Filter Bar */}
      <div className="shrink-0 space-y-4 pb-4 pt-1">
        <PageHeader
          title="Users"
          subtitle="Manage platform accounts, role-based access, and wallet balances."
        />

        {/* Filter Toolbar */}
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="relative min-w-[220px] flex-1 max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 rounded-lg border-border/60 bg-background pl-9 text-sm shadow-sm"
              placeholder="Search by email or name…"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
            />
          </div>

          <Select
            value={role || "All"}
            onValueChange={(val) =>
              setParams({ role: val === "all" ? null : val, page: "1" })
            }
          >
            <SelectTrigger className="h-9 w-[150px] rounded-lg border-border/60 bg-background text-sm shadow-sm">
              <SelectValue placeholder="Role" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Any Role</SelectItem>
              <SelectItem value="USER">User</SelectItem>
              <SelectItem value="SUPER_ADMIN">Super Admin</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={status || "All"}
            onValueChange={(val) =>
              setParams({ status: val === "all" ? null : val, page: "1" })
            }
          >
            <SelectTrigger className="h-9 w-[150px] rounded-lg border-border/60 bg-background text-sm shadow-sm">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Any Status</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="disabled">Suspended</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Full-Height Table Enclosure (calc(100vh - header & filter height)) */}
      <div className="flex min-h-0 flex-1 flex-col">
        <StateBox
          loading={loading}
          error={error?.message}
          empty={
            data && data.items.length === 0
              ? "No users match these filters."
              : null
          }
        >
          <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
            {/* Scrollable Data Table Body */}
            <div className="min-h-0 flex-1 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-muted/50 backdrop-blur-md">
                  <TableRow className="border-b border-border/60 hover:bg-transparent">
                    <TableHead className="h-10 px-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      User
                    </TableHead>
                    <TableHead className="h-10 px-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Role
                    </TableHead>
                    <TableHead className="h-10 px-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Status
                    </TableHead>
                    <TableHead className="h-10 px-5 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Wallet
                    </TableHead>
                    <TableHead className="h-10 px-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Joined
                    </TableHead>
                    <TableHead className="h-10 px-5 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.items.map((u) => {
                    const balance = u.wallet_balance ?? 0;
                    const isAdmin = u.role === "SUPER_ADMIN";
                    const isDisabled = u.disabled;

                    return (
                      <TableRow
                        key={u.id}
                        className="border-b border-border/40 transition-colors hover:bg-muted/20"
                      >
                        {/* Identity */}
                        <TableCell className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <Avatar
                              className={`h-9 w-9 border ${
                                isAdmin
                                  ? "border-amber-500/30 bg-amber-500/10"
                                  : "border-border/50 bg-muted/40"
                              }`}
                            >
                              <AvatarFallback
                                className={`text-xs font-semibold ${
                                  isAdmin
                                    ? "text-amber-700 dark:text-amber-400"
                                    : "text-foreground"
                                }`}
                              >
                                {getInitials(u.name, u.email)}
                              </AvatarFallback>
                            </Avatar>
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-foreground">
                                {u.name || "—"}
                              </div>
                              <div className="truncate text-xs text-muted-foreground">
                                {u.email}
                              </div>
                            </div>
                          </div>
                        </TableCell>

                        {/* Role */}
                        <TableCell className="px-5 py-3">
                          {isAdmin ? (
                            <Badge
                              variant="outline"
                              className="h-6 gap-1 border-amber-500/30 bg-amber-500/10 px-2 text-[11px] font-semibold text-amber-700 dark:text-amber-400"
                            >
                              <Shield className="h-3 w-3" />
                              Admin
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="h-6 gap-1 border-border/60 bg-muted/50 px-2 text-[11px] font-semibold text-muted-foreground"
                            >
                              <UsersIcon className="h-3 w-3" />
                              User
                            </Badge>
                          )}
                        </TableCell>

                        {/* Status */}
                        <TableCell className="px-5 py-3">
                          {isDisabled ? (
                            <Badge
                              variant="outline"
                              className="h-6 gap-1.5 border-rose-500/30 bg-rose-500/10 px-2 text-[11px] font-semibold text-rose-600 dark:text-rose-400"
                            >
                              <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                              Suspended
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="h-6 gap-1.5 border-emerald-500/30 bg-emerald-500/10 px-2 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400"
                            >
                              <span className="relative flex h-1.5 w-1.5">
                                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                              </span>
                              Active
                            </Badge>
                          )}
                        </TableCell>

                        {/* Wallet */}
                        <TableCell className="px-5 py-3 text-right">
                          <div className="inline-flex items-center justify-end gap-1.5">
                            <Wallet
                              className={`h-3.5 w-3.5 ${
                                balance > 0
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : balance < 0
                                    ? "text-rose-600 dark:text-rose-400"
                                    : "text-muted-foreground"
                              }`}
                            />
                            <span
                              className={`text-sm font-semibold tabular-nums ${
                                balance > 0
                                  ? "text-emerald-700 dark:text-emerald-400"
                                  : balance < 0
                                    ? "text-rose-600 dark:text-rose-400"
                                    : "text-muted-foreground"
                              }`}
                            >
                              {fmtINR(balance)}
                            </span>
                          </div>
                        </TableCell>

                        {/* Joined */}
                        <TableCell className="px-5 py-3 text-xs tabular-nums text-muted-foreground">
                          {fmtDateTime(u.created_at)}
                        </TableCell>

                        {/* Actions */}
                        <TableCell className="px-5 py-3 text-right">
                          <Button
                            variant="default"
                            size="sm"
                            className="h-8 gap-1.5 border-border/60 px-3 text-xs font-medium hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
                            onClick={() => router.push(`/users/${u.id}`)}
                          >
                            <Eye className="h-3.5 w-3.5" />
                            View Profile
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Pagination Footer (Pinned at absolute bottom of the card) */}
            {data && (
              <div className="shrink-0 border-t border-border/60 bg-muted/20 px-4 py-2.5">
                <Pager
                  total={data.total}
                  page={data.page}
                  pageSize={data.page_size}
                  onPage={(p) => setParams({ page: String(p) })}
                />
              </div>
            )}
          </div>
        </StateBox>
      </div>
    </div>
  );
}
