"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BadgeIndianRupee,
  Languages,
  SlidersHorizontal,
} from "lucide-react";

const providers = [
  { name: "OpenAI", logo: "/images/providers/openai.png", rate: "₹7.20/min" },
  { name: "Gemini", logo: "/images/providers/gemini.png", rate: "₹5.80/min" },
  { name: "Groq", logo: "/images/providers/grok.png", rate: "₹4.90/min" },
  { name: "Sarvam", logo: "/images/providers/sarvam.png", rate: "₹6.40/min" },
];

export default function ProvidersSection() {
  return (
    <section className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto max-w-[1440px] overflow-hidden rounded-[40px] bg-lavender-field p-7 sm:p-12 lg:p-16">
        <div className="grid gap-14 lg:grid-cols-[.9fr_1.1fr] lg:items-center">
          <div>
            <div className="text-xs font-bold uppercase tracking-[.12em] text-ultra-violet">
              Resilient by design
            </div>
            <h2 className="mt-5 max-w-[650px] text-[clamp(2.7rem,5vw,4.5rem)] font-semibold leading-[.97] tracking-[-.065em]">
              Use the AI model your calls need.
            </h2>
            <p className="mt-6 max-w-[560px] text-base leading-7 text-graphite sm:text-lg">
              Select one model for each agent based on language quality,
              response needs, and cost per minute.
            </p>
            <div className="mt-9 grid gap-3 sm:grid-cols-3">
              {[
                [Languages, "Language fit"],
                [BadgeIndianRupee, "Live rates"],
                [SlidersHorizontal, "Your choice"],
              ].map(([Icon, label]) => {
                const I = Icon as typeof Languages;
                return (
                  <motion.div
                    whileHover={{ y: -4 }}
                    key={label as string}
                    className="rounded-[22px] border border-white/70 bg-white/55 p-4 backdrop-blur"
                  >
                    <I className="h-4 w-4 text-voltage-violet" />
                    <div className="mt-5 text-sm font-semibold">
                      {label as string}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
          <div className="relative rounded-[32px] border border-white/75 bg-white/70 p-5 shadow-[0_30px_80px_rgba(95,37,158,.12)] backdrop-blur-xl sm:p-7">
            <div className="flex items-center justify-between border-b border-mist pb-5">
              <div>
                <div className="text-sm font-semibold">Model routing</div>
                <div className="mt-1 text-xs text-slate">
                  Configured for this agent
                </div>
              </div>
              <span className="rounded-full bg-lavender-field px-3 py-1.5 text-xs font-semibold text-ultra-violet">
                One selected
              </span>
            </div>
            <div className="mt-5 space-y-3">
              {providers.map((provider, index) => (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.08 }}
                  key={provider.name}
                  className="group flex items-center gap-4 rounded-[22px] border border-mist/70 bg-white p-4 transition-all hover:border-lavender-mist hover:shadow-[0_12px_30px_rgba(95,37,158,.08)]"
                >
                  <span className="grid h-11 w-11 place-items-center rounded-2xl bg-fog">
                    <Image
                      src={provider.logo}
                      alt={`${provider.name} logo`}
                      width={26}
                      height={26}
                      className="h-6 w-6 object-contain"
                    />
                  </span>
                  <div className="flex-1">
                    <div className="text-sm font-semibold">{provider.name}</div>
                    <div className="mt-1 text-xs text-slate">
                      {index === 0
                        ? "Selected for this agent"
                        : "Available model"}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold text-midnight-ink">
                      {provider.rate}
                    </div>
                    <div className="mt-0.5 text-[9px] uppercase tracking-wider text-slate">
                      Estimate
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
            <a
              href="#pricing"
              className="group mt-5 flex items-center justify-between rounded-full bg-midnight-ink px-5 py-4 text-sm font-semibold text-white"
            >
              See how usage is priced{" "}
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
