"use client";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BriefcaseBusiness,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { SectionHeading } from "./primitives";
const ease = [0.22, 1, 0.36, 1] as const;
const reveal = {
  hidden: { opacity: 0, y: 28 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease } },
};
export default function CreationSection() {
  return (
    <section id="platform" className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <motion.div
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: "-120px" }}
        variants={{ visible: { transition: { staggerChildren: 0.12 } } }}
        className="mx-auto max-w-[1440px]"
      >
        <motion.div variants={reveal}>
          <SectionHeading
            eyebrow="AI-guided setup"
            title={
              <>
                Describe the job.
                <br />
                Get the agent.
              </>
            }
            body="Explain what the agent should do in plain language. Voxura turns that requirement into a voice agent you can review and test."
          />
        </motion.div>
        <motion.div
          variants={reveal}
          className="mt-8 grid gap-2 rounded-[24px] bg-fog p-2 sm:grid-cols-3"
        >
          {[
            ["01", "Explain the requirement"],
            ["02", "Voxura builds the agent"],
            ["03", "Review and test"],
          ].map(([step, label]) => (
            <div
              key={step}
              className="flex items-center gap-3 rounded-[18px] bg-white px-4 py-3"
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-lavender-field text-[10px] font-bold text-voltage-violet">
                {step}
              </span>
              <span className="text-sm font-semibold text-midnight-ink">
                {label}
              </span>
            </div>
          ))}
        </motion.div>
        <motion.div
          variants={reveal}
          className="mt-4 grid overflow-hidden rounded-[40px] border border-lavender-mist/20 bg-[#f7f0ff] lg:grid-cols-[1.08fr_.92fr]"
        >
          <div className="noise relative min-h-[540px] overflow-hidden p-5 sm:p-9">
            <div className="absolute -left-32 top-20 h-80 w-80 rounded-full bg-voltage-violet/20 blur-[80px]" />
            <div className="absolute -right-20 bottom-0 h-72 w-72 rounded-full bg-magenta-spark/20 blur-[90px]" />
            <div className="relative mx-auto max-w-[560px] rounded-[28px] border border-white/80 bg-white/80 p-4 shadow-[0_24px_70px_rgba(95,37,158,.12)] backdrop-blur-xl sm:p-5">
              <div className="flex items-center gap-3 border-b border-mist/70 pb-4">
                <div className="grid h-9 w-9 place-items-center rounded-xl bg-voltage-violet text-white">
                  <Sparkles className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-semibold">Build with Voxura</div>
                  <div className="text-xs text-slate">
                    Agent setup assistant
                  </div>
                </div>
              </div>
              <div className="space-y-4 py-5 text-sm leading-6">
                <div className="max-w-[86%] rounded-2xl rounded-tl-md bg-fog p-4 text-graphite">
                  What should your new agent help your business with?
                </div>
                <div className="ml-auto max-w-[82%] rounded-2xl rounded-tr-md bg-voltage-violet p-4 text-white">
                  Qualify leads for our software business and follow up in Hindi
                  or English.
                </div>
                <div className="max-w-[90%] rounded-2xl rounded-tl-md bg-fog p-4 text-graphite">
                  Got it. I’ll prepare an outbound sales agent. Should it keep
                  calls brief or explore requirements in detail?
                </div>
                <div className="flex gap-2 pl-1">
                  <button className="rounded-full border border-voltage-violet/25 bg-white px-3 py-2 text-xs font-semibold text-ultra-violet">
                    Brief qualification
                  </button>
                  <button className="rounded-full border border-mist bg-white px-3 py-2 text-xs font-semibold text-graphite">
                    Detailed discovery
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-2xl border border-mist bg-white p-2 pl-4 text-sm text-slate">
                Describe how your agent should work…
                <button className="ml-auto grid h-9 w-9 place-items-center rounded-xl bg-midnight-ink text-white">
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
          <div className="relative flex flex-col justify-between bg-midnight-ink p-7 text-white sm:p-10">
            <div>
              <div className="mb-8 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-[.14em] text-lavender-mist">
                  Agent prepared
                </span>
                <span className="rounded-full bg-white/10 px-3 py-1.5 text-xs">
                  Draft
                </span>
              </div>
              <div className="flex items-center gap-4">
                <div className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-voltage-violet to-magenta-spark">
                  <BriefcaseBusiness className="h-7 w-7" />
                </div>
                <div>
                  <h3 className="text-2xl font-semibold tracking-[-.03em]">
                    Outbound sales
                  </h3>
                  <p className="mt-1 text-sm text-white/55">
                    Lead qualification agent
                  </p>
                </div>
              </div>
              <div className="mt-10 space-y-1">
                {[
                  ["Goal", "Qualify software leads"],
                  ["Direction", "Outbound calls"],
                  ["Languages", "Hindi + English"],
                  ["Tone", "Clear and concise"],
                  ["Calls", "Stored for review"],
                ].map(([key, value]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between border-b border-white/10 py-4 text-sm"
                  >
                    <span className="text-white/50">{key}</span>
                    <span className="font-medium">{value}</span>
                  </div>
                ))}
              </div>
            </div>
            <button className="mt-10 flex items-center justify-between rounded-xl bg-white px-5 py-4 text-sm font-semibold text-midnight-ink transition-transform hover:-translate-y-0.5">
              Continue configuration <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </motion.div>
      </motion.div>
    </section>
  );
}
