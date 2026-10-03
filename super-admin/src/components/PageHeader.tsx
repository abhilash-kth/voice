"use client";
import { useState } from "react";

export default function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
      <div>
        <h1 className="text-xl font-bold">{title}</h1>
        {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

export function StateBox({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: string | null;
  children: React.ReactNode;
}) {
  if (loading) {
    return (
      <div className="card p-8 text-center text-sm text-gray-500 animate-pulse">
        Loading…
      </div>
    );
  }
  if (error) {
    return (
      <div className="card p-5 border-red-500/30 bg-red-500/5 text-sm text-red-300">
        ⚠ {error}
      </div>
    );
  }
  if (empty) {
    return (
      <div className="card p-8 text-center text-sm text-gray-500">
        {empty}
      </div>
    );
  }
  return <>{children}</>;
}

export function useBusy() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const run = async <T,>(fn: () => Promise<T>, okMsg = "Saved ✓") => {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      const out = await fn();
      setMsg(okMsg);
      setTimeout(() => setMsg(""), 3000);
      return out;
    } catch (e) {
      setErr((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, err, run, setErr, setMsg };
}
