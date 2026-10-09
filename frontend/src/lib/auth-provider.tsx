"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { login, logout, me, type User } from "@/lib/index";

type AuthCtx = {
  user: User | null;
  loading: boolean; // true until /me has answered
  signIn: (body: { email: string; password: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // restore the session: the browser sends the cookie, the backend says who it is
  useEffect(() => {
    let cancelled = false;
    me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(async (e) => {
        if (cancelled) return;
        setUser(null);
        if (e?.status === 401) {
          // stale cookie: have the backend clear it, then go to login
          await logout().catch(() => {});
          router.replace("/login");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function signIn(body: { email: string; password: string }) {
    const { user: u } = await login(body); // throws on wrong password
    setUser(u);
    router.replace("/");
    router.refresh();
  }

  async function signOut() {
    try {
      await logout();
    } finally {
      setUser(null);
      router.replace("/login");
      router.refresh();
    }
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
