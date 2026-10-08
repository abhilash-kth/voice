"use client";
import { clearToken, User } from "@/lib/api";

export type Tab = "call" | "campaigns" | "agents" | "billing" | "calls";

const TABS: { id: Tab; label: string }[] = [
  { id: "call", label: "📞 Call" },
  { id: "campaigns", label: "📣 Campaigns" },
  { id: "agents", label: "🤖 Agents" },
  { id: "billing", label: "💳 Wallet" },
  { id: "calls", label: "📊 Calls" },
];

/** Sticky app header: brand, tab nav (desktop + mobile), wallet pill, logout. */
export default function TopBar({
  user, tab, onTab, balance, mobileMenuOpen, onMobileMenu, onLogout,
}: {
  user: User;
  tab: Tab;
  onTab: (t: Tab) => void;
  balance: number;
  mobileMenuOpen: boolean;
  onMobileMenu: (open: boolean) => void;
  onLogout: () => void;
}) {
  const logout = () => {
    clearToken();
    onLogout();
  };

  return (
    <header className="border-b border-gray-800/80 bg-gray-900/70 backdrop-blur-xl sticky top-0 z-50">
      <div className="px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-lg font-black shadow-lg shadow-blue-600/20 shrink-0">
            K
          </div>
          <div className="hidden sm:block min-w-0">
            <h1 className="font-bold text-[15px] leading-tight tracking-tight">Voice Agent SaaS</h1>
            <p className="text-[11px] text-gray-400 truncate">Self-service multilingual agents on LiveKit</p>
          </div>
          <div className="sm:hidden">
            <h1 className="font-bold text-sm">Voice SaaS</h1>
          </div>
        </div>

        {/* Desktop nav */}
        <div className="hidden lg:flex items-center gap-3">
          <nav className="flex bg-gray-800/60 p-1 rounded-xl border border-gray-700/50 backdrop-blur">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => onTab(t.id)}
                className={`px-3.5 py-2 text-[13px] font-semibold rounded-lg transition-all ${
                  tab === t.id
                    ? "bg-white text-gray-900 shadow-md"
                    : "text-gray-400 hover:text-white hover:bg-gray-700/50"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-3 pl-3 border-l border-gray-800">
            <div className="flex items-center gap-2.5 bg-gray-800/80 border border-gray-700/50 rounded-xl px-3 py-2">
              <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 text-xs">₹</div>
              <div className="leading-tight">
                <p className="text-[11px] text-gray-400 font-medium">Balance</p>
                <p className="text-sm font-bold text-white">₹{balance.toFixed(2)}</p>
              </div>
              <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse ml-1" />
            </div>

            <div className="text-right leading-tight hidden xl:block">
              <div className="font-semibold text-sm truncate max-w-[140px]">{user.name || user.email}</div>
              <div className="text-[11px] text-gray-500">Auto-deduct per call</div>
            </div>

            {user.role === "SUPER_ADMIN" && (
              <a
                href={process.env.NEXT_PUBLIC_ADMIN_URL || "http://localhost:3002"}
                className="text-xs text-amber-300 hover:text-amber-200 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/40 rounded-lg px-3 py-2 transition-colors"
                title="Open the Super Admin console"
              >
                Admin
              </a>
            )}

            <button
              onClick={logout}
              className="text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg px-3 py-2 transition-colors"
            >
              Logout
            </button>
          </div>
        </div>

        {/* Mobile: wallet + menu */}
        <div className="flex lg:hidden items-center gap-2">
          <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-xl px-2.5 py-1.5">
            <span className="text-[11px] font-bold text-emerald-400">₹{balance.toFixed(2)}</span>
          </div>
          <button
            onClick={() => onMobileMenu(!mobileMenuOpen)}
            className="w-9 h-9 rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-400"
          >
            {mobileMenuOpen ? "✕" : "☰"}
          </button>
        </div>
      </div>

      {/* Mobile menu drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-t border-gray-800 bg-gray-900/95 backdrop-blur-xl px-4 py-4 space-y-4">
          <nav className="grid grid-cols-3 gap-2">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => {
                  onTab(t.id);
                  onMobileMenu(false);
                }}
                className={`px-3 py-2.5 text-[13px] font-semibold rounded-xl border transition-all ${
                  tab === t.id
                    ? "bg-white text-gray-900 border-white shadow"
                    : "bg-gray-800 border-gray-700 text-gray-400"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center justify-between pt-3 border-t border-gray-800">
            <div>
              <p className="text-sm font-semibold">{user.name || user.email}</p>
              <p className="text-[11px] text-gray-500">Balance auto-deducts per call</p>
            </div>
            <button
              onClick={logout}
              className="text-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-400"
            >
              Logout
            </button>
          </div>
        </div>
      )}

      {/* Mobile secondary nav — scrollable */}
      <div className="lg:hidden border-t border-gray-800/50 bg-gray-900/50 px-2 py-2 overflow-x-auto scrollbar-hide">
        <div className="flex gap-1.5 w-max">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => onTab(t.id)}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-full whitespace-nowrap border transition-all ${
                tab === t.id
                  ? "bg-white text-gray-900 border-white"
                  : "bg-gray-800 border-gray-700 text-gray-400"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
