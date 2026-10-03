"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, setToken } from "@/lib/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const router = useRouter();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const out = await login({ email: email.trim(), password });
      if (out.user?.role !== "SUPER_ADMIN") {
        setErr("This account is not a SUPER_ADMIN. Use the customer dashboard instead.");
        return;
      }
      setToken(out.token);
      router.replace("/");
    } catch (e2) {
      setErr((e2 as Error).message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-b from-gray-950 via-gray-950 to-gray-900">
      <form onSubmit={submit} className="card w-full max-w-sm p-8 animate-fade-in-up">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center text-lg font-black">
            S
          </div>
          <div>
            <h1 className="text-lg font-bold leading-tight">Super Admin</h1>
            <p className="text-[11px] text-gray-500 leading-tight">Voice Agent SaaS — platform console</p>
          </div>
        </div>

        <label className="block text-xs text-gray-400 font-medium mb-1.5">Admin email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="input mb-4"
          autoComplete="username"
          placeholder="admin@yourdomain.com"
        />

        <label className="block text-xs text-gray-400 font-medium mb-1.5">Password</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="input mb-5"
          autoComplete="current-password"
          placeholder="••••••••"
        />

        {err && (
          <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
            ⚠ {err}
          </div>
        )}

        <button type="submit" className="btn w-full justify-center" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="mt-4 text-[10px] text-gray-600 leading-relaxed">
          Only accounts with role <code className="text-gray-400">SUPER_ADMIN</code> can sign in here. All
          admin actions are written to the audit log. Provider secrets are write-only and shown masked.
        </p>
      </form>
    </div>
  );
}
