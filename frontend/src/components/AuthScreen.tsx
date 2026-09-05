"use client";

import { useState } from "react";
import { login, register, setToken, User } from "@/lib/api";

interface Props {
  onAuth: (user: User) => void;
}

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

  return (
    <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-gray-900 p-8 rounded-3xl border border-gray-800 shadow-2xl">
        <div className="flex items-center justify-center gap-2 mb-6">
          <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-2xl font-bold">K</div>
          <div>
            <h1 className="font-bold text-xl">Voice Agent SaaS</h1>
            <p className="text-xs text-gray-400">Login to configure &amp; call your agents</p>
          </div>
        </div>

        <div className="flex gap-2 mb-6 bg-gray-800 p-1 rounded-xl">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 py-2 rounded-lg text-sm font-semibold ${mode === m ? "bg-blue-600" : "text-gray-400"}`}
            >
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {mode === "register" && (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm"
            />
          )}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm"
          />
        </div>

        {err && <p className="text-red-400 text-sm mt-3">{err}</p>}

        <button
          onClick={submit}
          disabled={busy}
          className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl mt-5 disabled:opacity-50"
        >
          {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <p className="text-center text-[11px] text-gray-500 mt-4">
          Demo mode — new accounts start with ₹0 and must recharge to place calls.
        </p>
      </div>
    </div>
  );
}
