"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { login, logout } from "@/lib/auth";
import { User } from "./api";

const USER_KEY = "user";

type AuthCtx = {
  user: User | null;
  loading: boolean; // true until the saved user has been read
  signIn: (body: { email: string; password: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // restore the user after a page refresh
  useEffect(() => {
    try {
      const saved = localStorage.getItem(USER_KEY);
      if (saved) setUser(JSON.parse(saved));
    } catch {}
    setLoading(false);
  }, []);

  async function signIn(body: { email: string; password: string }) {
    const u = await login(body); // throws on wrong password, the login page shows the message
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setUser(u);
    router.replace("/"); // CHANGE to your home page
    router.refresh();
  }

  async function signOut() {
    await logout();
    localStorage.removeItem(USER_KEY);
    setUser(null);
    router.replace("/login");
    router.refresh();
  }

  return (
    <Ctx.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
