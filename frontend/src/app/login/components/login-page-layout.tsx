"use client";

import { useState } from "react";
import {
  MessageSquare,
  BrainCircuit,
  Megaphone,
  Wallet,
  Loader2,
  AudioLines,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { register, User } from "@/lib/index";
import { useAuth } from "@/lib/auth-provider";

const FEATURES = [
  {
    icon: MessageSquare,
    title: "Human-like conversations",
  },
  {
    icon: BrainCircuit,
    title: "Your choice of AI brain",
  },
  {
    icon: Megaphone,
    title: "Bulk campaigns in minutes",
  },
  {
    icon: Wallet,
    title: "Wallet-driven billing",
  },
];

export default function LoginLayout() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const { signIn } = useAuth();

  const submit = async () => {
    setErr("");
    if (!email || !password) return setErr("Email and password are required.");
    setBusy(true);
    try {
      if (mode === "register") {
        await register({ email, password, name }); // creates the account only
      }
      await signIn({ email, password }); // sets the cookie and goes to "/"
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* ── Left: brand panel ── */}
      <div className="relative hidden h-full w-[48%] flex-col justify-between overflow-hidden p-12 lg:flex xl:p-14">
        {/* Themed overlays */}
        <div className="absolute inset-0 bg-primary/80 mix-blend-multiply" />
        <div className="absolute inset-0 bg-gradient-to-br from-primary via-primary/90 to-black/70" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-black/20" />
        {/* Soft glow orbs */}
        <div className="absolute -left-20 top-1/4 h-72 w-72 rounded-full bg-primary-foreground/10 blur-3xl" />
        <div className="absolute -right-10 bottom-1/4 h-56 w-56 rounded-full bg-primary-foreground/5 blur-3xl" />
        {/* Dot grid */}
        <div
          className="absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
            backgroundSize: "20px 20px",
            color: "white",
          }}
        />

        {/* Brand */}
        <div className="relative z-10 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-foreground text-primary shadow-sm">
            <AudioLines className="h-5 w-5" />
          </div>
          <span className="text-xl font-bold tracking-tight text-primary-foreground">
            Voxura
          </span>
        </div>

        {/* Hero + features */}
        <div className="relative z-10 max-w-md">
          <h1 className="mb-10 text-3xl font-extrabold leading-[1] tracking-tight text-primary-foreground xl:text-4xl">
            Put a voice agent
            <br />
            on every phone call.
          </h1>

          <div className="space-y-3">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="flex items-center gap-3 rounded-xl border border-primary-foreground/10 bg-primary-foreground/5 px-3.5 py-3 backdrop-blur-sm"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary-foreground/15 text-primary-foreground">
                  <f.icon className="h-4 w-4" />
                </div>
                <span className="text-xs font-semibold text-primary-foreground">
                  {f.title}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Spacer bottom to balance justify-between */}
        <div className="relative z-10" />
      </div>

      {/* ── Right: auth form ── */}
      <div className="flex h-full flex-1 items-center justify-center bg-background p-6 sm:p-10">
        <div className="w-full max-w-[380px]">
          {/* Mobile brand */}
          <div className="mb-10 flex items-center justify-center gap-2.5 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <AudioLines className="h-5 w-5" />
            </div>
            <span className="text-xl font-bold tracking-tight text-foreground">
              Voxura
            </span>
          </div>

          <div className="mb-8 space-y-1.5">
            <h2 className="text-2xl font-bold tracking-tight text-foreground">
              {mode === "login" ? "Welcome back" : "Create an account"}
            </h2>
            <p className="text-sm text-muted-foreground">
              {mode === "login"
                ? "Sign in to your Voxura workspace."
                : "Set up your workspace in under two minutes."}
            </p>
          </div>

          {/* Mode toggle */}
          <div className="mb-6 grid grid-cols-2 rounded-lg border border-border/60 bg-muted/40 p-1">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                  setErr("");
                }}
                className={`rounded-md py-2 text-sm font-medium transition-all ${
                  mode === m
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m === "login" ? "Sign in" : "Register"}
              </button>
            ))}
          </div>

          {/* Fields */}
          <div className="space-y-4">
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label
                  htmlFor="name"
                  className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  Full name
                </Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Priya Sharma"
                  className="h-10 border-input bg-background text-foreground placeholder:text-muted-foreground focus-visible:ring-1"
                  autoComplete="name"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <Label
                htmlFor="email"
                className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Email
              </Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="h-10 border-input bg-background text-foreground placeholder:text-muted-foreground focus-visible:ring-1"
                autoComplete="email"
              />
            </div>

            <div className="space-y-1.5">
              <Label
                htmlFor="password"
                className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Password
              </Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="••••••••"
                className="h-10 border-input bg-background text-foreground placeholder:text-muted-foreground focus-visible:ring-1"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
              />
            </div>
          </div>

          {err && (
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{err}</span>
            </div>
          )}

          <Button
            className="mt-6 h-10 w-full font-semibold"
            onClick={submit}
            disabled={busy}
          >
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            New accounts start with a ₹0 wallet. Recharge to place calls.
          </p>
        </div>
      </div>
    </div>
  );
}
