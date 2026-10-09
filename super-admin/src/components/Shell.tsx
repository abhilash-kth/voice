"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { logout, me, type ApiUser } from "@/lib/api";
import AppSidebar from "@/components/AppSidebar";

export default function Shell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    me()
      .then((u) => {
        if (u.role !== "SUPER_ADMIN") {
          logout();
          router.replace("/login");
          return;
        }
        setUser(u);
        setReady(true);
      })
      .catch(() => {
        logout();
        router.replace("/login");
      });
  }, [router]);

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  if (!ready || !user) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background">
        <div className="relative flex h-10 w-10 items-center justify-center">
          <span className="absolute inset-0 animate-ping rounded-full bg-primary/10 opacity-75" />
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card shadow-xs">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
          </div>
        </div>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Verifying admin session…
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <AppSidebar user={user} onLogout={handleLogout} />
      <main className="min-w-0 flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-[1400px] p-2 md:p-4">{children}</div>
      </main>
    </div>
  );
}
