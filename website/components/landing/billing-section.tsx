"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useInView } from "framer-motion";
import {
  ArrowRight,
  Phone,
  Plus,
  ReceiptText,
  WalletCards,
} from "lucide-react";
import { SectionHeading } from "./primitives";

const calls = [
  { label: "Receptionist call", time: "01:08", cost: 18 },
  { label: "Sales qualification", time: "02:14", cost: 31 },
  { label: "Support call", time: "04:32", cost: 54 },
  { label: "HR follow-up", time: "01:46", cost: 23 },
];

function CasinoBalance({ value }: { value: number }) {
  const [displayed, setDisplayed] = useState(value);
  const displayedRef = useRef(value);

  useEffect(() => {
    const from = displayedRef.current;
    const difference = value - from;
    const startedAt = performance.now();
    const duration = 900;
    let frame = 0;

    const update = (now: number) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = Math.round(from + difference * eased);

      if (next !== displayedRef.current) {
        displayedRef.current = next;
        setDisplayed(next);
      }

      if (progress < 1) frame = requestAnimationFrame(update);
    };

    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  const characters = displayed.toLocaleString("en-IN").split("");

  return (
    <span
      className="inline-flex h-[1em] items-center overflow-hidden align-middle leading-none tabular-nums"
      aria-label={`₹${displayed.toLocaleString("en-IN")}`}
    >
      {characters.map((character, index) => (
        <span
          key={`place-${index}`}
          className={
            character === ","
              ? "relative inline-grid w-[.25em] place-items-center"
              : "relative inline-grid w-[.57em] place-items-center"
          }
        >
          <AnimatePresence initial={false} mode="popLayout">
            <motion.span
              key={`${index}-${character}`}
              initial={{ y: -34, opacity: 0, filter: "blur(3px)" }}
              animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
              exit={{
                y: 34,
                opacity: 0,
                filter: "blur(3px)",
                position: "absolute",
              }}
              transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
              className="leading-none"
            >
              {character}
            </motion.span>
          </AnimatePresence>
        </span>
      ))}
    </span>
  );
}

export default function BillingSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const inView = useInView(sectionRef, { once: true, margin: "-15%" });
  const [step, setStep] = useState(0);
  const callIndex = useRef(0);

  useEffect(() => {
    if (!inView) return;
    const timer = window.setInterval(() => {
      const nextStep = callIndex.current + 1;
      setStep(nextStep);
      callIndex.current = nextStep >= calls.length ? 0 : nextStep;
    }, 2000);

    return () => window.clearInterval(timer);
  }, [inView]);

  return (
    <section
      ref={sectionRef}
      id="pricing"
      className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20"
    >
      <div className="mx-auto max-w-[1440px]">
        <SectionHeading
          eyebrow="Wallet billing"
          title={
            <>
              Add to your <span className="text-primary">Wallet</span>.
              <br />
              Use it per minute.
            </>
          }
          body="See the rate before a call and the exact deduction after it. Your wallet keeps usage visible as calls happen."
        />

        <div className="mt-10 grid gap-4 md:grid-cols-[.85fr_1.15fr]">
          <div className="relative flex min-h-[445px] flex-col justify-between overflow-hidden rounded-[34px] bg-voltage-violet p-7 text-white sm:p-9">
            <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-lavender-mist/30 blur-[70px]" />

            <div className="relative">
              <div className="flex items-center justify-between">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white/15">
                  <WalletCards className="h-5 w-5" />
                </span>
                <span className="rounded-full bg-white/15 px-3 py-1.5 text-xs font-semibold">
                  Active wallet
                </span>
              </div>

              <div className="mt-9 text-sm text-white/60">Wallet balance</div>
              <div className="mt-2 flex h-[82px] items-center">
                <div className="flex items-center whitespace-nowrap text-[clamp(3rem,6vw,5.2rem)] font-semibold leading-none tracking-[-.065em]">
                  <span className="inline-flex h-[1em] items-center leading-none">
                    ₹
                  </span>
                  <CasinoBalance value={inView ? 12500 : 0} />
                </div>
              </div>
            </div>

            <div className="relative pt-8">
              <p className="text-sm font-semibold leading-6 text-white">
                Simple per-minute pricing.
                <br />
                <span className="font-normal text-white/60">
                  Your wallet updates after every completed call.
                </span>
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <button className="rounded-full bg-white px-5 py-3 text-sm font-semibold text-voltage-violet transition-transform hover:-translate-y-1">
                  Recharge wallet
                </button>
                <a
                  href="/pricing"
                  className="group inline-flex items-center gap-2 rounded-full bg-white/12 px-5 py-3 text-sm font-semibold text-white"
                >
                  How pricing works
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </a>
              </div>
            </div>
          </div>

          <div className="h-[445px] overflow-hidden rounded-[34px] border border-mist bg-white p-6 sm:p-8">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-bold uppercase tracking-[.14em] text-slate">
                  Live usage
                </div>
                <h3 className="mt-2 text-2xl font-semibold tracking-[-.03em]">
                  Deductions as calls finish
                </h3>
              </div>
              <ReceiptText className="h-6 w-6 text-voltage-violet" />
            </div>

            <div className="mt-7 h-[292px] overflow-hidden">
              <AnimatePresence initial={false} mode="popLayout">
                {calls.slice(0, step).map((item, index) => {
                  const isNewest = index === step - 1;
                  return (
                    <motion.div
                      layout="position"
                      key={item.label}
                      initial={isNewest ? { opacity: 0, x: 90 } : false}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -60 }}
                      transition={{
                        layout: { duration: 0.36, ease: [0.22, 1, 0.36, 1] },
                        x: { duration: 0.46, ease: [0.22, 1, 0.36, 1] },
                        opacity: { duration: 0.28 },
                      }}
                      className="flex h-[58px] items-center gap-3 border-b border-mist/70"
                    >
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-fog text-voltage-violet">
                        <Phone className="h-4 w-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold">
                          {item.label}
                        </div>
                        <div className="mt-0.5 text-xs text-slate">
                          {item.time}
                        </div>
                      </div>
                      <span className="text-xs font-semibold text-slate">
                        − ₹{item.cost}
                      </span>
                    </motion.div>
                  );
                })}
              </AnimatePresence>

              {step < calls.length && (
                <motion.div
                  layout
                  className="flex h-[58px] items-center gap-3 text-xs text-slate"
                >
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-dashed border-mist">
                    <Plus className="h-4 w-4" />
                  </span>
                  Waiting for the next completed call…
                </motion.div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
