"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { RefreshCcw } from "lucide-react";

export default function ErrorPage() {
  const router = useRouter();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center text-foreground">
      <h1 className="text-3xl font-semibold tracking-tight">
        Something went wrong
      </h1>

      <p className="text-muted-foreground">Please try again later.</p>

      <Button onClick={() => router.push("/login")}>
        <RefreshCcw /> Try Again
      </Button>
    </main>
  );
}
