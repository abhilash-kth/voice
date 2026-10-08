"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { me, clearToken, type ApiUser } from "@/lib/api";

const NAV = [
  { href: "", label: "Overview", icon: "📊" },
  { href: "users", label: "Users", icon: "👥" },
  { href: "models", label: "Models", icon: "🧠" },
  { href: "providers", label: "Providers", icon: "🔌" },
  { href: "api-keys", label: "API Keys", icon: "🔑" },
  { href: "billing", label: "Billing", icon: "💰" },
  { href: "plans", label: "Plans", icon: "🗂️" },
  { href: "usage", label: "Usage", icon: "📈" },
  { href: "audit-logs", label: "Audit Logs", icon: "🧾" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [ready, setReady] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    me()
      .then((u) => {
        if (u.role !== "SUPER_ADMIN") {
          clearToken();
          router.replace("/login");
          return;
        }
        setUser(u);
        setReady(true);
      })
      .catch(() => {
        clearToken();
        router.replace("/login");
      });
  }, [router]);

  if (!ready || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500 text-sm">
        Verifying admin session…
      </div>
    );
  }

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-gray-800 bg-gray-900/80 backdrop-blur flex flex-col sticky top-0 h-screen">
        <div className="px-4 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center text-sm font-black text-white">
              S
            </div>
            <div>
              <div className="text-sm font-bold leading-tight">Super Admin</div>
              <div className="text-[10px] text-gray-500 leading-tight">Voice Agent SaaS</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV.map((n) => {
            const active = pathname === `/${n.href}`.replace(/\/$/, "") || (n.href === "" && pathname === "/");
            return (
              <Link
                key={n.href}
                href={`/${n.href}`}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-[13px] font-semibold transition-colors ${
                  active
                    ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                    : "text-gray-400 hover:text-white hover:bg-gray-800 border border-transparent"
                }`}
              >
                <span className="text-base">{n.icon}</span>
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-gray-800">
          <div className="text-[11px] text-gray-500 truncate mb-1.5" title={user.email}>
            {user.email}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="pill pill-amber flex-1">SUPER_ADMIN</span>
            <button
              onClick={() => {
                clearToken();
                router.replace("/login");
              }}
              className="text-[11px] px-2.5 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-400 hover:text-white hover:bg-gray-700"
            >
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <main className="flex-1 min-w-0 p-6 max-w-[1400px]">{children}</main>
    </div>
  );
}
