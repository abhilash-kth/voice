"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Brain,
  Plug,
  Key,
  CreditCard,
  BarChart3,
  ScrollText,
  LogOut,
  Shield,
  ChevronRight,
} from "lucide-react";
import type { ApiUser } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const NAV = [
  { href: "", label: "Overview", icon: LayoutDashboard },
  { href: "users", label: "Users", icon: Users },
  { href: "models", label: "Models", icon: Brain },
  { href: "providers", label: "Providers", icon: Plug },
  { href: "api-keys", label: "API Keys", icon: Key },
  { href: "billing", label: "Billing", icon: CreditCard },
  { href: "plans", label: "Plans", icon: CreditCard },
  { href: "usage", label: "Usage", icon: BarChart3 },
  { href: "audit-logs", label: "Audit Logs", icon: ScrollText },
] as const;

export default function AppSidebar({
  user,
  onLogout,
}: {
  user: ApiUser;
  onLogout: () => void;
}) {
  const pathname = usePathname();

  const isActive = (href: string) =>
    pathname === `/${href}`.replace(/\/$/, "") ||
    (href === "" && pathname === "/");

  const initials = (user.name || "SA").split("@")[0].slice(0, 2).toUpperCase();

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-border/60 bg-card">
      <div className="flex h-14 items-center gap-3 border-b border-border/60 px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <span className="text-sm font-bold tracking-tight">S</span>
        </div>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-semibold text-foreground">
            Super Admin
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            Voice Agent SaaS
          </p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-3">
        <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
          Platform
        </div>
        <div className="flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active = isActive(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={`/${item.href}`}
                className={cn(
                  "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary" />
                )}
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    active
                      ? "text-primary"
                      : "text-muted-foreground group-hover:text-foreground",
                  )}
                  strokeWidth={active ? 2.25 : 2}
                />
                <span className="truncate">{item.label}</span>
                {active && (
                  <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-40" />
                )}
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="mt-auto border-t border-border/60 p-3">
        <div className="flex items-center gap-2.5 rounded-lg border border-border/50 bg-muted/30 p-2">
          <Avatar className="h-8 w-8 border border-border/60">
            <AvatarFallback className="bg-background text-[11px] font-semibold text-foreground">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p
              className="truncate text-xs font-medium text-foreground"
              title={user.email}
            >
              {user.email}
            </p>
            <Badge
              variant="outline"
              className="mt-0.5 h-4 gap-1 border-amber-500/25 bg-primary/10 px-1.5 text-[9px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400"
            >
              <Shield className="h-2.5 w-2.5" />
              {user.name}
            </Badge>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
            onClick={onLogout}
            aria-label="Logout"
          >
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </aside>
  );
}
