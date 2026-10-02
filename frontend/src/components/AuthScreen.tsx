"use client";

import { useState } from "react";
import { login, register, setToken, User } from "@/lib/api";

interface Props {
  onAuth: (user: User) => void;
}

const FEATURES = [
  {
    icon: "🗣️",
    title: "Human-like conversations",
    desc: "Sub-second turn-taking, natural barge-in, and 11+ Indian languages out of the box.",
  },
  {
    icon: "🧠",
    title: "Your choice of AI brain",
    desc: "OpenAI, Groq, Google Gemini, Sarvam — with per-provider fallback and live pricing.",
  },
  {
    icon: "📣",
    title: "Bulk campaigns in minutes",
    desc: "Upload a CSV of leads, pick an agent, and the system dials, speaks, and bills for you.",
  },
  {
    icon: "💳",
    title: "Wallet-driven billing",
    desc: "Recharge once — every call auto-deducts from the balance, down to the last paisa.",
  },
];

export default function AuthScreen({ onAuth }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr("");
    if (!email || !password) return setErr("Email and password are required.");
    setBusy(true);
    try {
      const fn = mode === "login" ? login : register;
      const res = await fn({ email, password, name });
      setToken(res.token);
      onAuth(res.user);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    "w-full bg-gray-800/70 border border-gray-700/70 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all";

  return (
    <div className="min-h-screen bg-[#07070c] text-white flex">
      {/* ---- Left: brand hero (desktop only) ---- */}
      <div className="hidden lg:flex flex-col justify-between flex-1 relative overflow-hidden p-12 xl:p-16">
        {/* ambient background */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-40 -left-40 w-[520px] h-[520px] bg-blue-600/20 rounded-full blur-[140px]" />
          <div className="absolute bottom-0 right-0 w-[420px] h-[420px] bg-violet-600/15 rounded-full blur-[140px]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.05)_1px,transparent_0)] bg-[size:28px_28px]" />
        </div>

        <div className="relative flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-xl font-black shadow-lg shadow-blue-600/30">
            K
          </div>
          <div>
            <p className="font-bold text-lg tracking-tight leading-none">Voice Agent SaaS</p>
            <p className="text-[11px] text-gray-400 mt-1 uppercase tracking-[0.2em]">Conversational AI Platform</p>
          </div>
        </div>

        <div className="relative max-w-lg">
          <span className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-blue-300 bg-blue-500/10 border border-blue-500/20 rounded-full px-3 py-1.5 mb-6">
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
            Self-hosted • Production ready
          </span>
          <h1 className="text-4xl xl:text-5xl font-black tracking-tight leading-[1.1] mb-5">
            Put a voice agent
            <br />
            <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-violet-400 bg-clip-text text-transparent">
              on every phone call.
            </span>
          </h1>
          <p className="text-gray-400 text-[15px] leading-relaxed mb-10">
            Build multilingual AI agents that answer and dial real phone numbers —
            with natural interruptions, instant replies, and pay-as-you-go billing.
          </p>

          <div className="space-y-4">
            {FEATURES.map((f) => (
              <div key={f.title} className="flex items-start gap-3.5">
                <div className="w-9 h-9 rounded-xl bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-base shrink-0">
                  {f.icon}
                </div>
                <div>
                  <p className="text-sm font-semibold">{f.title}</p>
                  <p className="text-[13px] text-gray-500 leading-snug mt-0.5">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-6 text-[11px] text-gray-600">
          <span>LiveKit WebRTC core</span>
          <span className="w-1 h-1 bg-gray-700 rounded-full" />
          <span>Deepgram STT</span>
          <span className="w-1 h-1 bg-gray-700 rounded-full" />
          <span>Chirp 3 &amp; Sarvam voices</span>
          <span className="w-1 h-1 bg-gray-700 rounded-full" />
          <span>INR billing</span>
        </div>
      </div>

      {/* ---- Right: auth card ---- */}
      <div className="flex-1 lg:max-w-[480px] xl:max-w-[520px] flex items-center justify-center p-6 sm:p-10 relative">
        <div className="absolute inset-0 lg:hidden pointer-events-none">
          <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[420px] h-[420px] bg-blue-600/15 rounded-full blur-[120px]" />
        </div>

        <div className="relative w-full max-w-sm">
          {/* mobile brand */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-8">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-xl font-black shadow-lg shadow-blue-600/30">
              K
            </div>
            <div>
              <p className="font-bold text-lg tracking-tight leading-none">Voice Agent SaaS</p>
              <p className="text-[11px] text-gray-400 mt-1">Talking AI for your business</p>
            </div>
          </div>

          <div className="bg-gray-900/80 backdrop-blur-xl p-7 sm:p-8 rounded-3xl border border-gray-800 shadow-2xl shadow-black/40">
            <h2 className="text-xl font-bold tracking-tight">
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h2>
            <p className="text-[13px] text-gray-500 mt-1 mb-6">
              {mode === "login"
                ? "Sign in to manage agents, campaigns and wallet."
                : "Start building voice agents in under two minutes."}
            </p>

            <div className="grid grid-cols-2 gap-1 mb-6 bg-gray-800/80 p-1 rounded-xl border border-gray-700/50">
              {(["login", "register"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    setMode(m);
                    setErr("");
                  }}
                  className={`py-2.5 rounded-lg text-[13px] font-semibold transition-all ${
                    mode === m
                      ? "bg-white text-gray-900 shadow-md"
                      : "text-gray-400 hover:text-white"
                  }`}
                >
                  {m === "login" ? "Sign in" : "Register"}
                </button>
              ))}
            </div>

            <div className="space-y-3.5">
              {mode === "register" && (
                <div>
                  <label className="text-xs font-medium text-gray-400 mb-1.5 block">Full name</label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Priya Sharma"
                    className={inputCls}
                  />
                </div>
              )}
              <div>
                <label className="text-xs font-medium text-gray-400 mb-1.5 block">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className={inputCls}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-400 mb-1.5 block">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  placeholder="••••••••"
                  className={inputCls}
                />
              </div>
            </div>

            {err && (
              <div className="mt-4 text-[13px] bg-red-500/10 border border-red-500/25 text-red-300 rounded-xl px-3.5 py-2.5">
                {err}
              </div>
            )}

            <button
              onClick={submit}
              disabled={busy}
              className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold py-3 rounded-xl mt-6 disabled:opacity-60 shadow-lg shadow-blue-600/25 transition-all active:scale-[0.98]"
            >
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                  Please wait…
                </span>
              ) : mode === "login" ? (
                "Sign in →"
              ) : (
                "Create account →"
              )}
            </button>

            <p className="text-center text-[11px] text-gray-600 mt-5 leading-relaxed">
              New accounts start with a ₹0 wallet.
              <br />
              Recharge inside the dashboard to start placing calls.
            </p>
          </div>

          <p className="text-center text-[11px] text-gray-700 mt-6">
            © 2026 Voice Agent SaaS • Built on LiveKit
          </p>
        </div>
      </div>
    </div>
  );
}
