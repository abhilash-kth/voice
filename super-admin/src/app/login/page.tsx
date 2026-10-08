"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, AlertCircle, Loader2, Lock } from "lucide-react";
import { login, setToken } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

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
    <div className="relative min-h-screen flex items-center justify-center p-4 bg-background selection:bg-primary selection:text-primary-foreground overflow-hidden">
      {/* Radial accent ambient background */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-background to-background"
      />

      <Card className="relative w-full max-w-sm border-border/60 shadow-lg">
        <CardHeader className="space-y-3 pb-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <ShieldCheck className="h-5 w-5" strokeWidth={2.25} />
            </div>
            <div className="min-w-0">
              <CardTitle className="text-lg font-bold tracking-tight">
                Super Admin
              </CardTitle>
              <CardDescription className="text-xs text-muted-foreground">
                Voice Agent SaaS — platform console
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1.5">
              <Label
                htmlFor="admin-email"
                className="text-xs font-medium text-muted-foreground"
              >
                Admin email
              </Label>
              <Input
                id="admin-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                placeholder="admin@yourdomain.com"
                className="h-9 text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <Label
                htmlFor="admin-password"
                className="text-xs font-medium text-muted-foreground"
              >
                Password
              </Label>
              <Input
                id="admin-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
                className="h-9 text-sm"
              />
            </div>

            {err && (
              <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/10 px-3.5 py-3 text-xs font-medium text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <span className="leading-relaxed">{err}</span>
              </div>
            )}

            <Button
              type="submit"
              className="w-full h-9 text-xs font-semibold"
              disabled={busy}
            >
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  Signing in…
                </>
              ) : (
                <>
                  <Lock className="mr-2 h-3.5 w-3.5" />
                  Sign in
                </>
              )}
            </Button>
          </form>

          <p className="mt-6 text-[11px] leading-relaxed text-muted-foreground/80">
            Only accounts with role{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-foreground">
              SUPER_ADMIN
            </code>{" "}
            can sign in here. All admin actions are written to the audit log.
            Provider secrets are write-only and shown masked.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}