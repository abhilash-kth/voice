"use client";
import Link from "next/link";
import { ArrowRight, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
export function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mb-4 flex items-center gap-2 text-caption font-bold uppercase text-voltage-violet",
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-voltage-violet" />
      {children}
    </div>
  );
}

export function ArrowButton({
  children,
  dark = false,
  href = "#",
}: {
  children: React.ReactNode;
  dark?: boolean;
  href?: string;
}) {
  return (
    <a
      href={href}
      className={cn(
        "group inline-flex min-h-12 items-center justify-center gap-3 rounded-full px-6 py-3 text-base font-semibold transition-all duration-300 active:scale-[.98]",
        dark
          ? "bg-midnight-ink text-white hover:bg-graphite"
          : "bg-voltage-violet text-white shadow-subtle hover:-translate-y-0.5 hover:bg-ultra-violet hover:shadow-[0_12px_30px_rgba(134,47,231,.22)]",
      )}
    >
      {children}
      <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
    </a>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  body,
  align = "left",
}: {
  eyebrow: string;
  title: React.ReactNode;
  body?: string;
  align?: "left" | "center";
}) {
  return (
    <div
      className={cn(
        "max-w-[720px]",
        align === "center" && "mx-auto text-center",
      )}
    >
      <Eyebrow className={cn(align === "center" && "justify-center")}>
        {eyebrow}
      </Eyebrow>
      <h2 className="text-[clamp(2.65rem,4.3vw,4.2rem)] font-semibold leading-[1.06] tracking-[-0.045em] text-midnight-ink">
        {title}
      </h2>
      {body && (
        <p className="mt-5 max-w-[610px] text-base leading-7 text-slate sm:text-lg">
          {body}
        </p>
      )}
    </div>
  );
}

export function LogoMark() {
  return (
    <Link
      href="/"
      className="group flex items-center gap-2.5 font-semibold tracking-[-0.03em] text-midnight-ink"
    >
      <span className="relative grid h-8 w-8 place-items-center overflow-hidden rounded-[10px] bg-voltage-violet text-white shadow-subtle transition-transform duration-300 group-hover:rotate-6">
        <span className="absolute inset-0 bg-[radial-gradient(circle_at_70%_20%,rgba(255,255,255,.7),transparent_35%)]" />
        <Radio className="relative h-4 w-4" />
      </span>
      <span className="text-lg">Voxura</span>
    </Link>
  );
}
