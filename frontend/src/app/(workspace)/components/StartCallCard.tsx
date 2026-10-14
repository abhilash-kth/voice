"use client";

import { useRouter } from "next/navigation";
import { ArrowRight, Headphones, Mic2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function StartCallCard() {
  const router = useRouter();

  return (
    <section className="relative isolate overflow-hidden rounded-2xl bg-gradient-to-r from-emerald-600 via-green-700 to-teal-800 text-white shadow-md shadow-emerald-950/10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
      >
        <div className="absolute -right-16 -top-28 h-64 w-64 rounded-full bg-emerald-300/20 blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(110deg,transparent_40%,rgba(255,255,255,0.08)_75%,transparent)]" />
      </div>

      <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="hidden h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-white/20 bg-white/10 text-emerald-50 shadow-inner sm:flex">
            <Headphones className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="mb-1 inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-100/80">
              <Mic2 className="h-3 w-3" /> Voice workspace
            </div>
            <h2 className="text-xl font-bold tracking-tight sm:text-2xl">
              Ready to make a call?
            </h2>
            <p className="mt-1 text-sm text-emerald-50/80">
              Open the call workspace to choose an agent and get set up.
            </p>
          </div>
        </div>

        <Button
          type="button"
          onClick={() => router.push("/call")}
          className="h-11 shrink-0 gap-2 rounded-xl bg-white px-5 font-semibold text-emerald-800 shadow-sm hover:bg-emerald-50"
        >
          Start a call now
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </section>
  );
}
