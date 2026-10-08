"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  AudioLines,
  LayoutDashboard,
  PhoneCall,
  Megaphone,
  Bot,
  Wallet,
  History,
  LogOut,
  type LucideIcon,
} from "lucide-react";

import { type User } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Sidebar,
  SidebarBody,
  SidebarLink,
  useSidebar,
} from "@/components/ui/sidebar";

type NavItem = { href: string; label: string; icon: LucideIcon };

const WORKSPACE_NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/call", label: "Live Call", icon: PhoneCall },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/calls", label: "Call History", icon: History },
];

const FINANCE_NAV: NavItem[] = [
  { href: "/billing", label: "Wallet", icon: Wallet },
];

interface AppSidebarProps {
  user: User;
  onSignOut: () => void;
}

function NavSection({ label, items }: { label: string; items: NavItem[] }) {
  const pathname = usePathname();
  const { open } = useSidebar();

  const isActive = (href: string) =>
    href === "/"
      ? pathname === "/"
      : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="flex w-full flex-col gap-1">
      {/* Section Header */}
      <p
        className={cn(
          "text-[10px] font-bold uppercase tracking-wider text-white/50 transition-all duration-200",
          open
            ? "mb-1.5 h-auto px-3 opacity-100"
            : "m-0 h-0 overflow-hidden px-0 opacity-0",
        )}
      >
        {label}
      </p>

      {items.map((item) => {
        const active = isActive(item.href);

        return (
          <SidebarLink
            key={item.href}
            link={{
              label: item.label,
              href: item.href,
              icon: (
                <item.icon
                  className={cn(
                    "size-5 shrink-0 transition-colors",
                    active
                      ? "!text-white"
                      : "!text-white/70 group-hover/sidebar:!text-white",
                  )}
                />
              ),
            }}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group/sidebar !m-0 flex h-11 w-full items-center overflow-hidden rounded-xl text-sm transition-all duration-150",
              // Open vs Collapsed alignment fix
              open ? "justify-start gap-3 px-3" : "justify-center gap-0 px-0",
              // Force text color overrides onto Aceternity's internal child spans
              active
                ? "bg-white/20 font-bold !text-white shadow-sm [&_span]:!text-white"
                : "!text-white/70 hover:bg-white/10 hover:!text-white [&_span]:!text-white/70 group-hover/sidebar:[&_span]:!text-white",
            )}
          />
        );
      })}
    </div>
  );
}

function SidebarInner({ user, onSignOut }: AppSidebarProps) {
  const { open } = useSidebar();
  const displayName = user.name || "Workspace User";
  const initial = (user.name || user.email || "U").charAt(0).toUpperCase();

  return (
    <>
      <div className="flex w-full min-w-0 flex-1 flex-col gap-5 overflow-x-hidden overflow-y-auto">
        {/* Brand Header */}
        <Link
          href="/"
          className={cn(
            "flex h-12 w-full min-w-0 items-center overflow-hidden rounded-xl transition-opacity hover:opacity-90",
            open ? "justify-start gap-3 px-2" : "justify-center px-0",
          )}
        >
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-primary shadow-sm">
            <AudioLines className="size-5" />
          </div>
          {open && (
            <span className="truncate text-lg font-bold tracking-tight text-white">
              Voxura
            </span>
          )}
        </Link>

        {/* Nav Groups */}
        <div className="flex w-full min-w-0 flex-col gap-5">
          <NavSection label="Workspace" items={WORKSPACE_NAV} />
          <NavSection label="Finance" items={FINANCE_NAV} />
        </div>
      </div>

      {/* User Footer */}
      <div
        className={cn(
          "mt-auto flex w-full min-w-0 items-center overflow-hidden border-t border-white/15 pt-3",
          open ? "justify-start gap-3 px-1" : "justify-center px-0",
        )}
      >
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-xs font-bold text-primary shadow-sm">
          {initial}
        </div>

        {open && (
          <>
            <div className="flex min-w-0 flex-1 flex-col leading-tight">
              <p className="truncate text-sm font-bold text-white">
                {displayName}
              </p>
              <p className="truncate text-[11px] text-white/70">
                {user.email}
              </p>
            </div>

            <button
              type="button"
              onClick={onSignOut}
              title="Log out"
              aria-label="Log out"
              className="shrink-0 rounded-lg p-2 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            >
              <LogOut className="size-4" />
            </button>
          </>
        )}
      </div>
    </>
  );
}

export default function AppSidebar({ user, onSignOut }: AppSidebarProps) {
  const [open, setOpen] = useState(false);
  return (
    <Sidebar open={open} setOpen={setOpen}>
      <SidebarBody
        className={cn(
          "justify-between gap-4 overflow-x-hidden overflow-y-auto border-r-0 p-3",
          "bg-primary text-white", // Solid Primary background
        )}
      >
        <SidebarInner user={user} onSignOut={onSignOut} />
      </SidebarBody>
    </Sidebar>
  );
}