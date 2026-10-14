"use client";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowRight, Check, Mic2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Eyebrow } from "./primitives";
const ease = [0.22, 1, 0.36, 1] as const;
const reveal = {
  hidden: { opacity: 0, y: 28 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease } },
};
export default function ConversationSection() {
  const bars = [
    22, 42, 31, 58, 70, 47, 33, 62, 78, 51, 26, 18, 48, 66, 39, 25, 54, 72, 60,
    33, 20, 44, 68, 49, 24,
  ];
  return (
    <section className="relative overflow-hidden bg-midnight-ink px-5 py-16 text-white sm:px-8 sm:py-20">
      <div className="mx-auto grid max-w-[1440px] items-center gap-16 lg:grid-cols-[.8fr_1.2fr]">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-100px" }}
          variants={reveal}
        >
          <Eyebrow className="text-lavender-mist">
            <span className="h-1.5 w-1.5 rounded-full bg-lavender-mist" />
            Natural conversation
          </Eyebrow>
          <h2 className="text-[clamp(2.7rem,4.5vw,3.8rem)] font-semibold leading-[1.03] tracking-[-.05em]">
            No awkward pause.
            <br />
            <span className="text-lavender-mist">No rigid phone tree.</span>
          </h2>
          <p className="mt-6 max-w-[520px] text-lg leading-8 text-white/60">
            Voxura listens, stops when the caller interrupts, and continues with
            the new context—so the conversation keeps moving.
          </p>
          <div className="mt-9 grid grid-cols-2 gap-x-8 gap-y-6">
            {[
              "Stops when callers speak",
              "Responds with new context",
              "Works inbound and outbound",
              "Stores the conversation",
            ].map((item) => (
              <div
                key={item}
                className="flex items-center gap-3 text-sm font-medium"
              >
                <span className="grid h-6 w-6 place-items-center rounded-full bg-white/10">
                  <Check className="h-3.5 w-3.5 text-lavender-mist" />
                </span>
                {item}
              </div>
            ))}
          </div>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, x: 40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8, ease }}
          className="relative"
        >
          <Image
            src="/images/voice-signal-art.png"
            alt="Abstract visualization of a voice becoming a digital signal"
            fill
            className="rounded-[40px] object-cover opacity-60"
            sizes="(max-width: 1024px) 100vw, 55vw"
          />
          <div className="absolute inset-0 rounded-[40px] bg-gradient-to-br from-midnight-ink/25 via-midnight-ink/65 to-midnight-ink/90" />
          <div className="relative overflow-hidden rounded-[32px] border border-white/15 bg-midnight-ink/45 p-6 shadow-[0_30px_80px_rgba(0,0,0,.25)] backdrop-blur-xl sm:p-8">
            <div className="flex items-center justify-between border-b border-white/10 pb-5">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-full bg-voltage-violet">
                  <Mic2 className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-semibold">Live conversation</div>
                  <div className="mt-1 text-xs text-white/45">
                    Caller and agent timing
                  </div>
                </div>
              </div>
              <span className="flex items-center gap-2 rounded-full bg-emerald-400/10 px-3 py-1.5 text-xs font-semibold text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />{" "}
                Active
              </span>
            </div>
            <div className="py-9">
              <div className="mb-2 flex justify-between text-[10px] font-bold uppercase tracking-[.16em] text-white/35">
                <span>Caller</span>
                <span>Agent</span>
              </div>
              <div className="flex h-28 items-center justify-center gap-1">
                {bars.map((bar, i) => (
                  <motion.span
                    key={i}
                    className={cn(
                      "w-1.5 rounded-full",
                      i < 12 ? "bg-white/75" : "bg-lavender-mist",
                    )}
                    animate={{
                      height: [
                        `${Math.max(8, bar * 0.45)}%`,
                        `${bar}%`,
                        `${Math.max(8, bar * 0.5)}%`,
                      ],
                    }}
                    transition={{
                      duration: 0.9 + (i % 4) * 0.12,
                      repeat: Infinity,
                      delay: i * 0.025,
                    }}
                  />
                ))}
              </div>
              <div className="relative mt-4 h-7">
                <div className="absolute inset-x-0 top-3 h-px bg-white/15" />
                <div className="absolute left-[43%] top-0 flex flex-col items-center">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-magenta-spark text-[10px] font-bold">
                    ↯
                  </span>
                  <span className="mt-2 whitespace-nowrap text-[10px] text-white/45">
                    Caller interrupts
                  </span>
                </div>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
              <div className="rounded-2xl bg-white/[.07] p-4 text-sm leading-6 text-white/70">
                “I need to change the date—”
              </div>
              <ArrowRight className="mx-auto h-4 w-4 rotate-90 text-white/30 sm:rotate-0" />
              <div className="rounded-2xl bg-voltage-violet/20 p-4 text-sm leading-6 text-lavender-field">
                “Of course. Which date works?”
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
