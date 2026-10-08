"use client";

import { useQuery } from "@tanstack/react-query";
import { me } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { Loader2 } from "lucide-react";
import AppSidebar from "@/components/AppSidebar";
import DashboardHeader from "@/components/DashboardHeader";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { signOut } = useAuth();

  const {
    data: user,
    isPending: checking,
    isError,
  } = useQuery({
    queryKey: ["me"],
    queryFn: me,
    retry: false,
  });

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-medium">Loading workspace...</p>
        </div>
      </div>
    );
  }

  if (isError || !user) return null;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <AppSidebar user={user} onSignOut={signOut} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <DashboardHeader />

        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto w-full max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
