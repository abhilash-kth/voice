"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import { adminStats, adminHealth, reloadConfig, type Stats, type AdminHealth } from "@/lib/api";

function Stat({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className="card card-hover p-5 animate-fade-in-up">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-2xl font-black mt-1.5 ${accent || "text-white"}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

// snapshot_ts arrives as Unix epoch seconds (float). Format to HH:MM:SS.
function fmtEpoch(ts?: number): string {
  if (!ts || !Number.isFinite(ts)) return "—";
  try {
    return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
  } catch {
    return "—";
  }
}

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<AdminHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();

  const load = () => {
    setLoading(true);
    setError("");
    Promise.all([adminStats(), adminHealth()])
      .then(([s, h]) => {
        setStats(s);
        setHealth(h);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Platform health and configuration snapshot at a glance"
      >
        <button className="btn-secondary text-xs" onClick={load} disabled={loading}>
          ↻ Refresh
        </button>
        <button
          className="btn-secondary text-xs"
          disabled={busy}
          onClick={() => run(async () => { await reloadConfig(); load(); }, "Config reloaded ✓")}
        >
          {busy ? "Reloading…" : "Reload config"}
        </button>
      </PageHeader>

      {(msg || err) && (
        <div className={`mb-4 p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
          {msg || err}
        </div>
      )}

      <StateBox loading={loading} error={error}>
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            <Stat label="Users" value={stats?.users ?? 0} sub="registered accounts" />
            <Stat label="Calls" value={stats?.calls ?? 0} sub="all-time records" />
            <Stat label="Wallet float" value={`₹${stats?.wallet_balance_total?.toFixed(2) ?? "0.00"}`} sub="sum of user balances" accent="text-emerald-300" />
            <Stat label="All-time recharges" value={`₹${stats?.wallet_recharge_total?.toFixed(2) ?? "0.00"}`} sub="gross top-ups" accent="text-blue-300" />
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
            <Stat label="Providers" value={`${stats?.enabled_providers ?? 0} / ${stats?.providers ?? 0}`} sub="enabled / total" />
            <Stat label="Catalog models" value={`${stats?.enabled_models ?? 0} / ${stats?.models ?? 0}`} sub="enabled / total" />
            <Stat
              label="Config snapshot"
              value={health?.snapshot_source === "db" ? "DB ✓" : health?.snapshot_source ?? "—"}
              sub={`as of ${fmtEpoch(health?.snapshot_ts)}${health?.snapshot_error ? " ⚠ " + health.snapshot_error : ""}`}
              accent={health?.snapshot_source === "db" ? "text-emerald-300" : "text-amber-300"}
            />
            <Stat label="Backend" value={health?.ok ? "Online ✓" : "Offline"} sub="FastAPI / Prisma" accent={health?.ok ? "text-emerald-300" : "text-red-300"} />
          </div>

          <div className="card p-5">
            <h2 className="text-sm font-bold mb-3">Quick actions</h2>
            <div className="flex flex-wrap gap-2 text-xs">
              <Link href="/users" className="btn-secondary">👥 Manage users</Link>
              <Link href="/models" className="btn-secondary">🧠 Provider models</Link>
              <Link href="/api-keys" className="btn-secondary">🔑 API keys</Link>
              <Link href="/billing" className="btn-secondary">💰 Billing config</Link>
              <Link href="/audit-logs" className="btn-secondary">🧾 Audit logs</Link>
            </div>
            <p className="mt-4 text-[11px] text-gray-500 leading-relaxed">
              Dynamic configuration (providers, models, pricing, API keys) lives in the database and is
              served via an in-memory snapshot — changes apply without redeploying. If the snapshot source
              shows <span className="text-amber-300">code</span>, the DB is unreachable and the platform fell
              back to static defaults.
            </p>
          </div>
        </>
      </StateBox>
    </>
  );
}
