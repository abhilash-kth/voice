"use client";

import { useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Languages, MessageCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

const voices = [
  {
    name: "Priya",
    language: "Hindi",
    native: "हिंदी",
    lang: "hi-IN",
    greeting: "नमस्ते, मैं आज आपकी कैसे मदद कर सकती हूँ?",
    image: "/images/voices/aanya-pro.jpg",
    surface: "#eee5ff",
  },
  {
    name: "Kabir",
    language: "English",
    native: "English",
    lang: "en-IN",
    greeting: "Hello, how can I help you today?",
    image: "/images/voices/kabir-pro.jpg",
    surface: "#e5edf2",
  },
  {
    name: "Meera",
    language: "Tamil",
    native: "தமிழ்",
    lang: "ta-IN",
    greeting: "வணக்கம், இன்று நான் உங்களுக்கு எப்படி உதவலாம்?",
    image: "/images/voices/meera-pro.jpg",
    surface: "#f5e6df",
  },
  {
    name: "Arjun",
    language: "Marathi",
    native: "मराठी",
    lang: "mr-IN",
    greeting: "नमस्कार, मी आज तुम्हाला कशी मदत करू शकतो?",
    image: "/images/voices/arjun-pro.jpg",
    surface: "#e4edf8",
  },
  {
    name: "Nisha",
    language: "Bengali",
    native: "বাংলা",
    lang: "bn-IN",
    greeting: "নমস্কার, আজ আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    image: "/images/voices/nisha-pro.jpg",
    surface: "#e5f1e9",
  },
  {
    name: "Dev",
    language: "Gujarati",
    native: "ગુજરાતી",
    lang: "gu-IN",
    greeting: "નમસ્તે, આજે હું તમને કેવી રીતે મદદ કરી શકું?",
    image: "/images/voices/dev-pro.jpg",
    surface: "#f4ecdc",
  },
  {
    name: "Tara",
    language: "Kannada",
    native: "ಕನ್ನಡ",
    lang: "kn-IN",
    greeting: "ನಮಸ್ಕಾರ, ಇಂದು ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
    image: "/images/voices/tara-pro.jpg",
    surface: "#f2e2e8",
  },
  {
    name: "Rohan",
    language: "Telugu",
    native: "తెలుగు",
    lang: "te-IN",
    greeting: "నమస్కారం, నేను ఈరోజు మీకు ఎలా సహాయం చేయగలను?",
    image: "/images/voices/rohan-pro.jpg",
    surface: "#e0f0ef",
  },
];

export default function VoiceLanguageSection() {
  const [selected, setSelected] = useState(0);
  const voice = voices[selected];

  return (
    <section
      id="agents"
      className="relative px-5 py-14 sm:px-8 sm:py-16 lg:py-20"
    >
      <span id="languages" className="absolute top-0" aria-hidden="true" />
      <div className="mx-auto max-w-[1440px]">
        <motion.div
          initial={{ opacity: 0, y: 22 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="grid gap-7 lg:grid-cols-[.9fr_1.1fr] lg:items-end"
        >
          <div>
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Voices and languages
            </div>
            <h2 className="mt-4 max-w-[720px] text-[clamp(2.7rem,4.8vw,4.7rem)] font-semibold leading-[.95] tracking-[-.065em]">
              A familiar voice for every caller.
            </h2>
          </div>
          <p className="max-w-[590px] text-base leading-7 text-slate sm:text-lg">
            Choose a voice for the language your customers use naturally. Each
            persona gives the conversation a clear, consistent identity.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-70px" }}
          transition={{ duration: 0.65 }}
          className="relative mt-11 overflow-hidden rounded-[38px] border border-[#e8def5] bg-[#f8f5fc] p-3 shadow-[0_28px_80px_rgba(54,31,79,.08)] sm:p-4"
        >
          <div className="pointer-events-none absolute -left-24 -top-28 h-80 w-80 rounded-full bg-lavender-field/75 blur-[95px]" />
          <div className="pointer-events-none absolute -bottom-40 right-[18%] h-80 w-80 rounded-full bg-amber-100/45 blur-[100px]" />

          <div className="relative grid gap-3 lg:grid-cols-[.42fr_.58fr]">
            <div className="rounded-[30px] bg-white/80 p-4 backdrop-blur-md sm:p-5">
              <div className="flex items-center justify-between border-b border-mist px-1 pb-4">
                <div>
                  <div className="text-sm font-semibold text-midnight-ink">
                    Choose a voice
                  </div>
                  <div className="mt-1 text-xs text-slate">
                    One persona for each language
                  </div>
                </div>
                <span className="grid h-10 w-10 place-items-center rounded-2xl bg-lavender-field text-voltage-violet">
                  <Languages className="h-4 w-4" />
                </span>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                {voices.map((item, index) => {
                  const active = selected === index;
                  return (
                    <button
                      key={item.name}
                      onClick={() => setSelected(index)}
                      className={cn(
                        "group relative flex min-h-[68px] items-center gap-3 overflow-hidden rounded-[19px] border p-2.5 text-left transition-all duration-300",
                        active
                          ? "border-lavender-mist bg-white shadow-[0_10px_28px_rgba(95,37,158,.1)]"
                          : "border-transparent bg-fog/65 hover:border-mist hover:bg-white",
                      )}
                    >
                      <span
                        className="relative h-11 w-11 shrink-0 overflow-hidden rounded-[14px]"
                        style={{ background: item.surface }}
                      >
                        <Image
                          src={item.image}
                          alt=""
                          fill
                          className="object-cover object-top mix-blend-multiply"
                          sizes="44px"
                        />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-semibold text-midnight-ink">
                          {item.name}
                        </span>
                        <span className="mt-1 block truncate text-[10px] text-slate">
                          {item.language} · {item.native}
                        </span>
                      </span>
                      {active && (
                        <motion.span
                          layoutId="voice-language-check"
                          className="absolute right-2 top-2 grid h-4 w-4 place-items-center rounded-full bg-voltage-violet text-white"
                        >
                          <Check className="h-2.5 w-2.5" />
                        </motion.span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="relative flex min-h-[405px] flex-col justify-between overflow-hidden rounded-[30px] bg-midnight-ink p-6 text-white sm:p-8 lg:p-10">
              <motion.div
                animate={{ scale: [1, 1.16, 1], x: [0, 28, 0], y: [0, -16, 0] }}
                transition={{
                  duration: 9,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="pointer-events-none absolute -right-16 -top-24 h-96 w-96 rounded-full bg-voltage-violet/35 blur-[95px]"
              />
              <div className="pointer-events-none absolute -bottom-36 left-[5%] h-80 w-80 rounded-full bg-[#c46fff]/20 blur-[95px]" />
              <div className="pointer-events-none absolute inset-0 opacity-[.045] [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:18px_18px]" />

              <div className="relative flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span
                    className="relative h-12 w-12 shrink-0 overflow-hidden rounded-2xl border border-white/10"
                    style={{ background: voice.surface }}
                  >
                    <Image
                      src={voice.image}
                      alt=""
                      fill
                      className="object-cover object-top mix-blend-multiply"
                      sizes="48px"
                    />
                  </span>
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-[.16em] text-white/40">
                      Language preview
                    </div>
                    <div className="mt-1 text-sm font-semibold">
                      {voice.name} · {voice.language}
                    </div>
                  </div>
                </div>
                <span className="rounded-full border border-white/10 bg-white/[.06] px-3 py-1.5 text-[10px] font-semibold text-white/55">
                  {voice.lang}
                </span>
              </div>

              <AnimatePresence mode="wait">
                <motion.div
                  key={voice.name}
                  initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: -12, filter: "blur(6px)" }}
                  transition={{ duration: 0.34 }}
                  className="relative py-10"
                >
                  <MessageCircle className="mb-6 h-6 w-6 text-lavender-mist" />
                  <blockquote className="max-w-[780px] text-[clamp(2rem,3.5vw,3.8rem)] font-semibold leading-[1.12] tracking-[-.045em]">
                    “{voice.greeting}”
                  </blockquote>
                  <div className="mt-6 flex items-center gap-2 text-xs text-white/40">
                    <Sparkles className="h-3.5 w-3.5 text-lavender-mist" />A
                    natural greeting written in {voice.language}
                  </div>
                </motion.div>
              </AnimatePresence>

              <div className="relative border-t border-white/10 pt-6">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-[.14em] text-white/35">
                      Selected combination
                    </div>
                    <div className="mt-2 text-sm font-semibold">
                      {voice.name} speaking {voice.language}
                    </div>
                  </div>
                  <div className="hidden items-end gap-1 sm:flex">
                    {Array.from({ length: 18 }).map((_, index) => (
                      <motion.span
                        key={index}
                        animate={{ height: [4, 7 + ((index * 9) % 18), 4] }}
                        transition={{
                          duration: 2.2,
                          repeat: Infinity,
                          delay: index * 0.04,
                          ease: "easeInOut",
                        }}
                        className="w-1 rounded-full bg-lavender-mist/45"
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        <p className="mt-4 text-xs text-slate">
          Illustrative voice personas and language previews. Final voice
          availability may vary by configuration.
        </p>
      </div>
    </section>
  );
}
