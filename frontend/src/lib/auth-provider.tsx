"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { login, logout, me, type User } from "@/lib/index";

type AuthCtx = {
  user: User | null;
  loading: boolean;
  signIn: (body: { email: string; password: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const {
    data: user,
    error,
    isPending,
  } = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await me();
      } catch (e) {
        // 401 just means "not logged in", so it is a valid answer, not an error
        if ((e as { status?: number }).status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 5 * 60_000,
  });

  // real failures only (backend down, 500, network)
  useEffect(() => {
    if (error) router.replace("/error");
  }, [error, router]);

  // logged out, but still on a protected page (for example a stale cookie)
  useEffect(() => {
    if (!isPending && user === null && !pathname.startsWith("/login")) {
      logout().catch(() => {}); // the backend clears the httpOnly cookie
      router.replace("/login");
    }
  }, [isPending, user, pathname, router]);

  async function signIn(body: { email: string; password: string }) {
    const { user: u } = await login(body);
    queryClient.setQueryData(["me"], u);
    router.replace("/");
    router.refresh();
  }

  async function signOut() {
    try {
      await logout();
    } finally {
      queryClient.setQueryData(["me"], null);
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <Ctx.Provider
      value={{ user: user ?? null, loading: isPending, signIn, signOut }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
