"use client";

import { useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Pause, Play, Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";

const voices = [
  {
    name: "Aanya",
    language: "Hindi + English",
    style: "Warm and clear",
    image: "/images/voices/aanya-pro.jpg",
    sample:
      "Namaste. Main Aanya bol rahi hoon. Aaj main aapki kis tarah madad kar sakti hoon?",
    lang: "hi-IN",
    surface: "#eee5ff",
  },
  {
    name: "Kabir",
    language: "English + Hindi",
    style: "Confident and concise",
    image: "/images/voices/kabir-pro.jpg",
    sample:
      "Hello, I’m Kabir. I can help answer your questions and guide you through the next step.",
    lang: "en-IN",
    surface: "#e5edf2",
  },
  {
    name: "Meera",
    language: "Tamil + English",
    style: "Calm and professional",
    image: "/images/voices/meera-pro.jpg",
    sample:
      "Vanakkam. I’m Meera. Tell me what you need help with and we’ll take it from there.",
    lang: "en-IN",
    surface: "#f5e6df",
  },
  {
    name: "Arjun",
    language: "English + Marathi",
    style: "Clear and friendly",
    image: "/images/voices/arjun-pro.jpg",
    sample: "Hello, I’m Arjun. Let’s quickly understand what you need today.",
    lang: "en-IN",
    surface: "#e4edf8",
  },
  {
    name: "Nisha",
    language: "Bengali + English",
    style: "Friendly and patient",
    image: "/images/voices/nisha-pro.jpg",
    sample:
      "Hello, I’m Nisha. I’m here to make this conversation simple and helpful.",
    lang: "en-IN",
    surface: "#e5f1e9",
  },
  {
    name: "Dev",
    language: "Gujarati + Hindi",
    style: "Direct and composed",
    image: "/images/voices/dev-pro.jpg",
    sample:
      "Namaste, I’m Dev. I’ll keep this brief and help you with the right next step.",
    lang: "en-IN",
    surface: "#f4ecdc",
  },
  {
    name: "Tara",
    language: "Kannada + English",
    style: "Professional and warm",
    image: "/images/voices/tara-pro.jpg",
    sample: "Hello, I’m Tara. How may I help with your request today?",
    lang: "en-IN",
    surface: "#f2e2e8",
  },
  {
    name: "Rohan",
    language: "Telugu + English",
    style: "Calm and reassuring",
    image: "/images/voices/rohan-pro.jpg",
    sample:
      "Hello, I’m Rohan. Share what you need, and I’ll guide you from here.",
    lang: "en-IN",
    surface: "#e0f0ef",
  },
];

export default function AgentsSection() {
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const voice = voices[selected];
  const choose = (index: number) => {
    window.speechSynthesis?.cancel();
    setPlaying(false);
    setSelected(index);
  };
  const speak = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    if (playing) {
      setPlaying(false);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(voice.sample);
    utterance.lang = voice.lang;
    utterance.rate = 0.92;
    utterance.onend = () => setPlaying(false);
    setPlaying(true);
    window.speechSynthesis.speak(utterance);
  };

  return (
    <section id="agents" className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto max-w-[1440px]">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end"
        >
          <div>
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Voice library
            </div>
            <h2 className="mt-4 max-w-[720px] text-[clamp(2.7rem,4.5vw,4.5rem)] font-semibold leading-[.96] tracking-[-.065em]">
              Find the voice that fits your business.
            </h2>
          </div>
          <p className="max-w-[450px] text-base leading-7 text-slate">
            Compare language, tone, and delivery—then hear the selected voice
            before your first call.
          </p>
        </motion.div>

        <div className="mt-10 grid gap-4 lg:grid-cols-[.4fr_.6fr]">
          <motion.div
            initial={{ opacity: 0, x: -24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="grid grid-cols-2 gap-2 rounded-[28px] border border-mist bg-fog p-2 sm:grid-cols-4 lg:grid-cols-2 lg:p-3"
          >
            {voices.map((item, index) => (
              <button
                key={item.name}
                onClick={() => choose(index)}
                className={cn(
                  "group flex min-w-0 items-center gap-3 rounded-[20px] border p-3 text-left transition-all duration-300",
                  selected === index
                    ? "border-lavender-mist bg-white shadow-[0_10px_28px_rgba(95,37,158,.09)]"
                    : "border-transparent hover:bg-white/70",
                )}
              >
                <span
                  className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full"
                  style={{ background: item.surface }}
                >
                  <Image
                    src={item.image}
                    alt=""
                    fill
                    className="object-cover object-top"
                    sizes="44px"
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-midnight-ink">
                    {item.name}
                  </span>
                  <span className="mt-0.5 block truncate text-[10px] text-slate">
                    {item.language}
                  </span>
                </span>
                {selected === index && (
                  <motion.span
                    layoutId="voice-check"
                    className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-voltage-violet text-white"
                  >
                    <Check className="h-3 w-3" />
                  </motion.span>
                )}
              </button>
            ))}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="relative min-h-[460px] overflow-hidden rounded-[32px] border border-mist"
            style={{ background: voice.surface }}
          >
            <AnimatePresence mode="wait">
              <motion.div
                key={voice.name}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.38 }}
                className="absolute inset-0 grid md:grid-cols-[1.05fr_.95fr]"
              >
                <div className="relative z-10 flex flex-col justify-between p-7 sm:p-9">
                  <div>
                    <div className="inline-flex items-center gap-2 rounded-full bg-white/70 px-3 py-2 text-[10px] font-bold uppercase tracking-[.12em] text-voltage-violet backdrop-blur">
                      <Volume2 className="h-3.5 w-3.5" />
                      Selected voice
                    </div>
                    <h3 className="mt-7 text-[clamp(2.4rem,4vw,4rem)] font-semibold leading-none tracking-[-.06em]">
                      {voice.name}
                    </h3>
                    <p className="mt-3 text-sm font-semibold text-graphite">
                      {voice.language} · {voice.style}
                    </p>
                    <blockquote className="mt-8 max-w-[570px] text-lg leading-8 text-graphite">
                      “{voice.sample}”
                    </blockquote>
                  </div>
                  <div className="mt-8 flex items-center gap-4">
                    <button
                      onClick={speak}
                      className="group inline-flex min-h-12 items-center gap-3 rounded-full bg-midnight-ink px-5 text-sm font-semibold text-white transition-all hover:-translate-y-1 hover:shadow-xl"
                    >
                      {playing ? (
                        <Pause className="h-4 w-4 fill-current" />
                      ) : (
                        <Play className="h-4 w-4 fill-current" />
                      )}
                      {playing ? "Stop preview" : "Play voice"}
                    </button>
                    <div className="flex h-7 items-center gap-0.5">
                      {Array.from({ length: 22 }).map((_, i) => (
                        <motion.span
                          key={i}
                          animate={{
                            height: playing ? [4, 7 + ((i * 9) % 20), 4] : 4,
                          }}
                          transition={{
                            duration: 0.7,
                            repeat: Infinity,
                            delay: i * 0.025,
                          }}
                          className="w-0.5 rounded-full bg-voltage-violet"
                        />
                      ))}
                    </div>
                  </div>
                </div>
                <div
                  className="relative hidden overflow-hidden md:block"
                  style={{ background: voice.surface }}
                >
                  <div className="absolute inset-x-[10%] bottom-0 top-[8%] rounded-t-[160px] bg-white/25" />
                  <Image
                    src={voice.image}
                    alt={`${voice.name}, illustrative AI voice persona`}
                    fill
                    priority={selected === 0}
                    className="object-cover object-center mix-blend-multiply [mask-image:linear-gradient(to_left,black_82%,transparent_100%)] drop-shadow-[0_24px_35px_rgba(17,24,39,.10)]"
                    sizes="(max-width:1024px) 0px,42vw"
                  />
                </div>
              </motion.div>
            </AnimatePresence>
          </motion.div>
        </div>
        <p className="mt-4 text-xs text-slate">
          Illustrative voice personas. Browser preview quality depends on the
          voices installed on your device.
        </p>
      </div>
    </section>
  );
}
