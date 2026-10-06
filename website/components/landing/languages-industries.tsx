"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, Languages, Play, Square } from "lucide-react";
import { cn } from "@/lib/utils";

const languages = [
  {
    name: "Hindi",
    native: "हिंदी",
    greeting: "नमस्ते, मैं आज आपकी कैसे मदद कर सकता हूँ?",
    lang: "hi-IN",
  },
  {
    name: "English",
    native: "English",
    greeting: "Hello, how can I help you today?",
    lang: "en-IN",
  },
  {
    name: "Marathi",
    native: "मराठी",
    greeting: "नमस्कार, मी आज तुम्हाला कशी मदत करू शकते?",
    lang: "mr-IN",
  },
  {
    name: "Tamil",
    native: "தமிழ்",
    greeting: "வணக்கம், இன்று நான் உங்களுக்கு எப்படி உதவலாம்?",
    lang: "ta-IN",
  },
  {
    name: "Telugu",
    native: "తెలుగు",
    greeting: "నమస్కారం, నేను ఈరోజు మీకు ఎలా సహాయం చేయగలను?",
    lang: "te-IN",
  },
  {
    name: "Kannada",
    native: "ಕನ್ನಡ",
    greeting: "ನಮಸ್ಕಾರ, ಇಂದು ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
    lang: "kn-IN",
  },
  {
    name: "Malayalam",
    native: "മലയാളം",
    greeting: "നമസ്കാരം, ഞാൻ എങ്ങനെ സഹായിക്കാം?",
    lang: "ml-IN",
  },
  {
    name: "Bengali",
    native: "বাংলা",
    greeting: "নমস্কার, আজ আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    lang: "bn-IN",
  },
  {
    name: "Gujarati",
    native: "ગુજરાતી",
    greeting: "નમસ્તે, આજે હું તમને કેવી રીતે મદદ કરી શકું?",
    lang: "gu-IN",
  },
  {
    name: "Punjabi",
    native: "ਪੰਜਾਬੀ",
    greeting: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਅੱਜ ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?",
    lang: "pa-IN",
  },
  {
    name: "Odia",
    native: "ଓଡ଼ିଆ",
    greeting: "ନମସ୍କାର, ଆଜି ମୁଁ ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି?",
    lang: "or-IN",
  },
];

export default function LanguagesIndustries() {
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false);
  const current = languages[active];

  const selectLanguage = (index: number) => {
    window.speechSynthesis?.cancel();
    setPlaying(false);
    setActive(index);
  };

  const speak = () => {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    if (playing) {
      setPlaying(false);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(current.greeting);
    utterance.lang = current.lang;
    utterance.rate = 0.9;
    utterance.onend = () => setPlaying(false);
    utterance.onerror = () => setPlaying(false);
    setPlaying(true);
    window.speechSynthesis.speak(utterance);
  };

  return (
    <section id="languages" className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto max-w-[1440px]">
        <div className="grid gap-8 lg:grid-cols-[.82fr_1.18fr] lg:items-end">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
          >
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Languages
            </div>
            <h2 className="mt-4 max-w-[620px] text-[clamp(2.7rem,5vw,4.6rem)] font-semibold leading-[.95] tracking-[-.065em]">
              Speak to every caller naturally.
            </h2>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.08 }}
            className="lg:pb-1"
          >
            <p className="max-w-[610px] text-base leading-7 text-slate sm:text-lg">
              One agent can hold clear conversations across 11+ Indian
              languages, so callers can continue in the language they are most
              comfortable using.
            </p>
            <a
              href="#final-cta"
              className="group mt-5 inline-flex items-center gap-2 text-sm font-semibold text-voltage-violet"
            >
              Request a language
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </a>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-70px" }}
          transition={{ duration: 0.65 }}
          className="relative mt-11 overflow-hidden rounded-[38px] border border-[#e8def5] bg-[#f8f5fc] p-3 shadow-[0_28px_80px_rgba(54,31,79,.08)] sm:p-4"
        >
          <div className="pointer-events-none absolute -left-20 -top-32 h-80 w-80 rounded-full bg-lavender-field/75 blur-[90px]" />
          <div className="pointer-events-none absolute -bottom-36 right-[20%] h-72 w-72 rounded-full bg-amber-100/45 blur-[100px]" />

          <div className="relative grid gap-3 lg:grid-cols-[.42fr_.58fr]">
            <div className="rounded-[30px] bg-white/75 p-5 backdrop-blur-md sm:p-6">
              <div className="flex items-center justify-between border-b border-mist pb-5">
                <div>
                  <div className="text-sm font-semibold text-midnight-ink">
                    Choose a language
                  </div>
                  <div className="mt-1 text-xs text-slate">
                    Preview how your agent sounds
                  </div>
                </div>
                <span className="grid h-10 w-10 place-items-center rounded-2xl bg-lavender-field text-voltage-violet">
                  <Languages className="h-4 w-4" />
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                {languages.map((item, index) => {
                  const selected = active === index;
                  return (
                    <button
                      key={item.name}
                      onClick={() => selectLanguage(index)}
                      className={cn(
                        "relative flex min-h-14 items-center justify-between overflow-hidden rounded-2xl px-3.5 text-left transition-colors",
                        selected
                          ? "text-white"
                          : "bg-fog/70 text-graphite hover:bg-lavender-field/60",
                      )}
                    >
                      {selected && (
                        <motion.span
                          layoutId="active-language"
                          className="absolute inset-0 rounded-2xl bg-midnight-ink"
                          transition={{
                            type: "spring",
                            stiffness: 380,
                            damping: 32,
                          }}
                        />
                      )}
                      <span className="relative min-w-0">
                        <span className="block truncate text-xs font-semibold">
                          {item.name}
                        </span>
                        <span
                          className={cn(
                            "mt-0.5 block truncate text-[11px]",
                            selected ? "text-white/55" : "text-slate",
                          )}
                        >
                          {item.native}
                        </span>
                      </span>
                      {selected && (
                        <Check className="relative h-3.5 w-3.5 shrink-0 text-lavender-mist" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="relative flex min-h-[430px] flex-col justify-between overflow-hidden rounded-[30px] bg-midnight-ink p-6 text-white sm:p-8 lg:p-10">
              <motion.div
                animate={{ scale: [1, 1.14, 1], x: [0, 24, 0], y: [0, -14, 0] }}
                transition={{
                  duration: 9,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="pointer-events-none absolute -right-16 -top-20 h-80 w-80 rounded-full bg-voltage-violet/35 blur-[85px]"
              />
              <div className="pointer-events-none absolute -bottom-28 left-[8%] h-72 w-72 rounded-full bg-[#c46fff]/20 blur-[90px]" />
              <div className="pointer-events-none absolute inset-0 opacity-[.045] [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:18px_18px]" />

              <div className="relative flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white/10 text-lavender-mist">
                    <Languages className="h-5 w-5" />
                  </span>
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-[.16em] text-white/40">
                      Live language preview
                    </div>
                    <div className="mt-1 text-sm font-semibold">
                      {current.name} · {current.native}
                    </div>
                  </div>
                </div>
                <span className="hidden rounded-full border border-white/10 bg-white/[.06] px-3 py-1.5 text-[10px] font-semibold text-white/55 sm:inline-flex">
                  {current.lang}
                </span>
              </div>

              <AnimatePresence mode="wait">
                <motion.div
                  key={current.name}
                  initial={{ opacity: 0, y: 14, filter: "blur(5px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: -10, filter: "blur(5px)" }}
                  transition={{ duration: 0.32 }}
                  className="relative py-9"
                >
                  <div className="text-[clamp(2rem,3.4vw,3.7rem)] font-semibold leading-[1.13] tracking-[-.045em] text-white">
                    “{current.greeting}”
                  </div>
                  <div className="mt-5 text-xs text-white/38">
                    A natural greeting in {current.name}
                  </div>
                </motion.div>
              </AnimatePresence>

              <div className="relative flex flex-col gap-5 border-t border-white/10 pt-6 sm:flex-row sm:items-center">
                <button
                  onClick={speak}
                  className="group inline-flex min-h-12 shrink-0 items-center justify-center gap-3 rounded-full bg-white px-5 text-sm font-semibold text-midnight-ink transition-transform hover:-translate-y-0.5"
                >
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-voltage-violet text-white">
                    {playing ? (
                      <Square className="h-3 w-3 fill-current" />
                    ) : (
                      <Play className="ml-0.5 h-3 w-3 fill-current" />
                    )}
                  </span>
                  {playing ? "Stop preview" : "Hear greeting"}
                </button>

                <div className="flex h-12 min-w-0 flex-1 items-center gap-[3px] overflow-hidden rounded-full bg-white/[.055] px-5">
                  {Array.from({ length: 38 }).map((_, index) => (
                    <motion.span
                      key={index}
                      animate={{
                        height: playing
                          ? [4, 9 + ((index * 11) % 25), 4]
                          : [3, 5 + ((index * 7) % 8), 3],
                      }}
                      transition={{
                        duration: playing ? 0.62 : 2.2,
                        repeat: Infinity,
                        delay: index * 0.022,
                        ease: "easeInOut",
                      }}
                      className={cn(
                        "w-[3px] shrink-0 rounded-full",
                        playing ? "bg-lavender-mist" : "bg-white/20",
                      )}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
