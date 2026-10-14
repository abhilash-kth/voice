"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Bot, Play, Radio } from "lucide-react";
import { ShaderBackground } from "@/components/ui/manu";

const ease = [0.22, 1, 0.36, 1] as const;

export default function Hero() {
  const [previewing, setPreviewing] = useState(false);
  const previewVoice = () => {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    if (previewing) {
      setPreviewing(false);
      return;
    }
    const sample = new SpeechSynthesisUtterance(
      "Namaste. Is this a good time for a quick conversation?",
    );
    sample.lang = "en-IN";
    sample.rate = 0.92;
    sample.onend = () => setPreviewing(false);
    setPreviewing(true);
    window.speechSynthesis.speak(sample);
  };
  return (
    <section id="top" className="px-4 pb-14 pt-22 sm:px-6 sm:pb-16 sm:pt-24">
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.9, ease }}
        className="noise relative isolate mx-auto min-h-[590px] max-w-[1440px] overflow-hidden rounded-[36px] bg-[#160925] px-5 pb-6 pt-12 text-white shadow-[0_40px_120px_rgba(71,28,120,.22)] [clip-path:inset(0_round_36px)] sm:rounded-[48px] sm:px-10 sm:pb-8 sm:pt-14 sm:[clip-path:inset(0_round_48px)]"
      >
        <ShaderBackground className="absolute inset-0 h-full w-full" />
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(18,7,31,.02),rgba(18,7,31,.20)_58%,rgba(18,7,31,.72))]" />
        <motion.div
          animate={{ x: [0, 30, 0], y: [0, -16, 0] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -left-24 top-12 h-72 w-72 rounded-full bg-voltage-violet/35 blur-[90px]"
        />
        <motion.div
          animate={{ x: [0, -28, 0], y: [0, 22, 0] }}
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -right-20 top-32 h-80 w-80 rounded-full bg-magenta-spark/20 blur-[110px]"
        />

        <div className="relative z-10 mx-auto flex max-w-[920px] flex-col items-center text-center">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25, duration: 0.6, ease }}
            className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2 text-xs font-semibold text-white/85 backdrop-blur-xl"
          >
            <Radio className="h-3.5 w-3.5 text-lavender-mist" /> AI voice agents
            for business
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.32, duration: 0.8, ease }}
            className="max-w-[900px] text-[clamp(3rem,6.6vw,6.3rem)] font-semibold leading-[.91] tracking-[-.072em]"
          >
            Voice agents for
            <br />
            <span className="text-white">every business call.</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.43, duration: 0.7, ease }}
            className="mt-7 max-w-[620px] text-base leading-7 text-white/65 sm:text-xl sm:leading-8"
          >
            Create multilingual AI agents for inbound calls and outbound
            campaigns. Pay only for the minutes you use.
          </motion.p>
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.52, duration: 0.7, ease }}
            className="mt-9 flex w-full flex-col justify-center gap-3 sm:w-auto sm:flex-row"
          >
            <a
              href="#final-cta"
              className="group inline-flex min-h-14 items-center justify-center gap-3 rounded-full bg-white px-7 text-sm font-semibold text-midnight-ink transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_16px_40px_rgba(255,255,255,.2)] active:translate-y-0"
            >
              Create your agent{" "}
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </a>
            <a
              href="#platform"
              className="group inline-flex min-h-14 items-center justify-center gap-3 rounded-full border border-white/20 bg-white/10 px-7 text-sm font-semibold text-white backdrop-blur-xl transition-all duration-300 hover:border-white/35 hover:bg-white/15"
            >
              See how it works{" "}
              <Play className="h-4 w-4 fill-current transition-transform group-hover:scale-110" />
            </a>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 38 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.65, duration: 0.9, ease }}
          className="relative z-10 mx-auto mt-8 max-w-[860px] rounded-[26px] border border-white/25 bg-white/[.10] p-3 shadow-[0_30px_90px_rgba(0,0,0,.28),inset_0_1px_0_rgba(255,255,255,.16)] backdrop-blur-2xl"
        >
          <div className="flex flex-col gap-5 rounded-[20px] border border-white/12 bg-[#10091b]/42 p-5 md:flex-row md:items-center">
            <div className="flex min-w-0 items-center gap-4 md:w-[245px]">
              <motion.div
                animate={{
                  boxShadow: [
                    "0 0 0 0 rgba(173,109,244,0)",
                    "0 0 0 9px rgba(173,109,244,.09)",
                    "0 0 0 0 rgba(173,109,244,0)",
                  ],
                }}
                transition={{ duration: 2.4, repeat: Infinity }}
                className="relative grid h-12 w-12 shrink-0 place-items-center rounded-full bg-voltage-violet"
              >
                <Bot className="h-5 w-5" />
                <span className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full border-2 border-[#24122f] bg-emerald-400" />
              </motion.div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">
                  Aarav · Sales agent
                </div>
                <div className="mt-1 text-xs text-white/45">
                  Hindi · Outbound
                </div>
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-bold uppercase tracking-[.14em] text-lavender-mist">
                Live sample
              </div>
              <p className="mt-2 truncate text-sm text-white/75">
                “Namaste, is this a good time for a quick conversation?”
              </p>
              <div className="mt-3 flex h-5 items-center gap-0.5">
                {Array.from({ length: 28 }).map((_, i) => (
                  <motion.span
                    key={i}
                    animate={{
                      height: previewing ? [3, 5 + ((i * 9) % 15), 3] : 3,
                    }}
                    transition={{
                      duration: 0.7,
                      repeat: Infinity,
                      delay: i * 0.025,
                    }}
                    className="w-0.5 rounded-full bg-lavender-mist"
                  />
                ))}
              </div>
            </div>
            <button
              onClick={previewVoice}
              className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-full bg-white px-5 text-sm font-semibold text-midnight-ink transition-all hover:-translate-y-1"
            >
              <Play className="h-4 w-4 fill-current" />
              {previewing ? "Stop voice" : "Hear Aarav"}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </section>
  );
}
