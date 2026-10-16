"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AudioLines,
  Bot,
  Pause,
  PhoneCall,
  Play,
  UserRound,
} from "lucide-react";
import { Eyebrow } from "./primitives";

const ease = [0.22, 1, 0.36, 1] as const;
const demoAudio =
  "https://ik.imagekit.io/qk2ww553c/ai-calling-agent/asutost%20agent.mp3";
const totalDuration = 157.36;

const turns = [
  {
    start: 3.72,
    end: 8.72,
    speaker: "agent",
    text: "Hello, my name is Ashutosh and I am calling from Kriscent Techno Hub. How may I help you today?",
  },
  {
    start: 9.16,
    end: 16.18,
    speaker: "caller",
    text: "Hello Ashutosh, I want to know more about Kriscent Techno Hub and what kind of services your company provides.",
  },
  {
    start: 19.08,
    end: 29.2,
    speaker: "agent",
    text: "Certainly. Kriscent provides web and mobile solutions, UI/UX design, digital marketing, AI and ML solutions, data engineering, consultancy, and more.",
  },
  {
    start: 29.38,
    end: 35.4,
    speaker: "caller",
    text: "That’s great. Do you also provide AI solutions such as AI voice agents and business automation?",
  },
  {
    start: 37.76,
    end: 45.46,
    speaker: "agent",
    text: "Sure. Kriscent builds AI calling agents for customer support, appointment booking, lead qualification, and business automation tasks.",
  },
  {
    start: 46.46,
    end: 57.72,
    speaker: "caller",
    text: "I’m planning to develop a product and want to integrate an AI voice agent. Can Kriscent help with the integration and technical support?",
  },
  {
    start: 59.66,
    end: 65.48,
    speaker: "agent",
    text: "Absolutely. Kriscent Techno Hub can assist with AI-agent integration and provide technical support throughout.",
  },
  {
    start: 66.5,
    end: 71.94,
    speaker: "caller",
    text: "If a business wants to use your services, how can they get started?",
  },
  {
    start: 74.16,
    end: 79.94,
    speaker: "agent",
    text: "Please share your name, company, contact number, and a brief description of your requirement to get started.",
  },
  {
    start: 80.54,
    end: 86.12,
    speaker: "caller",
    text: "Could you please tell me how I can contact your team for more information?",
  },
  { start: 88.24, end: 89.64, speaker: "agent", text: "Yes, tell me." },
  {
    start: 91.36,
    end: 94.82,
    speaker: "caller",
    text: "Could you please tell me how I can contact your team?",
  },
  {
    start: 97.02,
    end: 101.04,
    speaker: "agent",
    text: "Please share your contact details and requirement, and our team will reach out to you soon.",
  },
  {
    start: 101.68,
    end: 112.46,
    speaker: "caller",
    text: "I’ve shared my contact details. I want to integrate an AI voice agent into my product.",
  },
  {
    start: 114.82,
    end: 118.82,
    speaker: "agent",
    text: "Certainly. May I have your name and company name along with the contact number you shared?",
  },
  {
    start: 120.54,
    end: 131.74,
    speaker: "caller",
    text: "My name is Abhilash and my company name is Tepato.",
  },
  {
    start: 133.72,
    end: 138.48,
    speaker: "agent",
    text: "Noted, Abhilash. May I confirm the company name to complete the details?",
  },
  {
    start: 138.48,
    end: 140.28,
    speaker: "caller",
    text: "Tepato. My company name is Tepato.",
  },
  {
    start: 141.62,
    end: 148.02,
    speaker: "agent",
    text: "Got it. I have your contact details and integration requirement noted for our team to review.",
  },
  {
    start: 149.5,
    end: 152.3,
    speaker: "caller",
    text: "Thank you very much, Ashutosh. Have a great day.",
  },
  {
    start: 153.62,
    end: 157.36,
    speaker: "agent",
    text: "Thank you for calling us. It was nice talking to you. Goodbye.",
  },
] as const;

function formatTime(seconds: number) {
  const safe = Number.isFinite(seconds) ? seconds : 0;
  return `${Math.floor(safe / 60)}:${Math.floor(safe % 60)
    .toString()
    .padStart(2, "0")}`;
}

export default function ConversationSection() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);

  let activeIndex = 0;
  turns.forEach((turn, index) => {
    if (currentTime >= turn.start) activeIndex = index;
  });
  const activeTurn = turns[activeIndex];
  const agentSpeaking = activeTurn.speaker === "agent";
  const progress = Math.min((currentTime / totalDuration) * 100, 100);

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
      return;
    }
    try {
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  };

  const seek = (event: React.MouseEvent<HTMLButtonElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const next = ((event.clientX - bounds.left) / bounds.width) * totalDuration;
    audio.currentTime = next;
    setCurrentTime(next);
  };

  return (
    <section className="relative overflow-hidden bg-midnight-ink px-5 py-16 text-white sm:px-8 sm:py-20">
      <div className="pointer-events-none absolute left-[8%] top-[12%] h-80 w-80 rounded-full bg-voltage-violet/15 blur-[110px]" />
      <div className="pointer-events-none absolute bottom-[-15%] right-[8%] h-96 w-96 rounded-full bg-[#c46fff]/10 blur-[120px]" />

      <div className="relative mx-auto grid max-w-[1440px] items-center gap-10 lg:grid-cols-[.6fr_1.4fr]">
        <motion.div
          initial={{ opacity: 0, y: 28 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7, ease }}
        >
          <Eyebrow className="text-lavender-mist">
            <span className="h-1.5 w-1.5 rounded-full bg-lavender-mist" />
            Real AI call
          </Eyebrow>
          <h2 className="max-w-[540px] text-[clamp(2.7rem,4.5vw,4.4rem)] font-semibold leading-[1.02] tracking-[-.055em]">
            Hear an AI agent handle a real enquiry.
          </h2>
          <p className="mt-6 max-w-[470px] text-base leading-7 text-white/58 sm:text-lg sm:leading-8">
            Listen as the agent answers service questions, understands an
            integration requirement, and records the customer’s next step in one
            continuous call.
          </p>
          <div className="mt-7 inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/[.05] px-4 py-2.5 text-xs font-semibold text-white/60">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Real two-way voice recording
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 36 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8, ease }}
          className="relative overflow-hidden rounded-[34px] border border-white/12 bg-[linear-gradient(145deg,rgba(255,255,255,.09),rgba(255,255,255,.035))] p-3 shadow-[0_30px_90px_rgba(0,0,0,.28),inset_0_1px_0_rgba(255,255,255,.16)] backdrop-blur-xl"
        >
          <audio
            ref={audioRef}
            src={demoAudio}
            preload="metadata"
            onTimeUpdate={(event) =>
              setCurrentTime(event.currentTarget.currentTime)
            }
            onEnded={() => {
              setPlaying(false);
              setCurrentTime(0);
            }}
          />
          <div className="overflow-hidden rounded-[26px] border border-white/[.08] bg-[#12091f]/65">
            <div className="flex flex-col gap-4 border-b border-white/10 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-voltage-violet text-white">
                  <Bot className="h-5 w-5" />
                </span>
                <div>
                  <div className="text-sm font-semibold">
                    Live AI service enquiry
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-white/40">
                    <span>Ashutosh · AI agent</span>
                    <span>•</span>
                    <span>Customer</span>
                  </div>
                </div>
              </div>
              <span className="flex w-fit items-center gap-2 rounded-full bg-emerald-400/10 px-3 py-1.5 text-[10px] font-semibold text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                Real two-way call
              </span>
            </div>

            <div className="relative h-[310px] overflow-hidden px-5 py-6 sm:px-7">
              <div className="pointer-events-none absolute left-[8%] top-[6%] h-40 w-40 rounded-full bg-voltage-violet/15 blur-[65px]" />
              <div className="pointer-events-none absolute right-[7%] top-[8%] h-40 w-40 rounded-full bg-lavender-mist/10 blur-[65px]" />

              <div className="relative grid grid-cols-[auto_1fr_auto] items-center gap-4 sm:gap-7">
                <div className="flex flex-col items-center text-center">
                  <motion.div
                    animate={
                      playing && agentSpeaking
                        ? {
                            boxShadow: [
                              "0 0 0 0 rgba(134,47,231,.38)",
                              "0 0 0 14px rgba(134,47,231,0)",
                            ],
                          }
                        : {}
                    }
                    transition={{ duration: 1.4, repeat: Infinity }}
                    className={`relative grid h-16 w-16 place-items-center rounded-full border sm:h-20 sm:w-20 ${agentSpeaking && playing ? "border-lavender-mist/60 bg-voltage-violet text-white" : "border-white/10 bg-white/[.06] text-white/40"}`}
                  >
                    <Bot className="h-6 w-6 sm:h-7 sm:w-7" />
                    {agentSpeaking && playing && (
                      <span className="absolute -bottom-1 -right-1 grid h-6 w-6 place-items-center rounded-full border-2 border-[#12091f] bg-emerald-400 text-midnight-ink">
                        <AudioLines className="h-3 w-3" />
                      </span>
                    )}
                  </motion.div>
                  <div className="mt-3 text-xs font-semibold">Ashutosh</div>
                  <div className="mt-1 text-[9px] uppercase tracking-[.12em] text-lavender-mist">
                    AI agent
                  </div>
                </div>

                <div className="min-w-0">
                  <div className="mb-3 flex items-center justify-center gap-2 text-[9px] font-bold uppercase tracking-[.14em] text-white/35">
                    <PhoneCall className="h-3 w-3" />
                    {playing
                      ? agentSpeaking
                        ? "Agent speaking"
                        : "Caller speaking"
                      : "Ready to play"}
                  </div>
                  <div className="relative flex h-16 items-center justify-center gap-[3px] overflow-hidden rounded-full border border-white/[.06] bg-white/[.035] px-4">
                    <div className="absolute inset-x-0 top-1/2 h-px bg-white/10" />
                    {playing && (
                      <motion.div
                        initial={{ x: agentSpeaking ? "-120%" : "120%" }}
                        animate={{ x: agentSpeaking ? "220%" : "-220%" }}
                        transition={{
                          duration: 1.6,
                          repeat: Infinity,
                          ease: "linear",
                        }}
                        className="absolute top-1/2 h-px w-1/3 -translate-y-1/2 bg-gradient-to-r from-transparent via-lavender-mist to-transparent"
                      />
                    )}
                    {Array.from({ length: 34 }).map((_, index) => (
                      <motion.span
                        key={index}
                        animate={{
                          height: playing ? [4, 9 + ((index * 13) % 31), 4] : 4,
                        }}
                        transition={
                          playing
                            ? {
                                duration: 0.62,
                                repeat: Infinity,
                                delay: index * 0.025,
                                ease: "easeInOut",
                              }
                            : { duration: 0.2 }
                        }
                        className={`relative w-[3px] shrink-0 rounded-full ${agentSpeaking ? "bg-lavender-mist" : "bg-white/55"}`}
                      />
                    ))}
                  </div>
                  <div className="mx-auto mt-3 flex max-w-[210px] items-center gap-2">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${playing ? "bg-emerald-400" : "bg-white/20"}`}
                    />
                    <span className="h-px flex-1 bg-white/10" />
                    <span className="text-[9px] text-white/30">Connected</span>
                  </div>
                </div>

                <div className="flex flex-col items-center text-center">
                  <motion.div
                    animate={
                      playing && !agentSpeaking
                        ? {
                            boxShadow: [
                              "0 0 0 0 rgba(218,185,255,.3)",
                              "0 0 0 14px rgba(218,185,255,0)",
                            ],
                          }
                        : {}
                    }
                    transition={{ duration: 1.4, repeat: Infinity }}
                    className={`relative grid h-16 w-16 place-items-center rounded-full border sm:h-20 sm:w-20 ${!agentSpeaking && playing ? "border-lavender-mist/50 bg-lavender-field text-voltage-violet" : "border-white/10 bg-white/[.06] text-white/40"}`}
                  >
                    <UserRound className="h-6 w-6 sm:h-7 sm:w-7" />
                    {!agentSpeaking && playing && (
                      <span className="absolute -bottom-1 -left-1 grid h-6 w-6 place-items-center rounded-full border-2 border-[#12091f] bg-emerald-400 text-midnight-ink">
                        <AudioLines className="h-3 w-3" />
                      </span>
                    )}
                  </motion.div>
                  <div className="mt-3 text-xs font-semibold">Customer</div>
                  <div className="mt-1 text-[9px] uppercase tracking-[.12em] text-white/35">
                    Caller
                  </div>
                </div>
              </div>

              <div
                className={`relative mt-5 flex min-h-[88px] items-center ${agentSpeaking ? "justify-start" : "justify-end"}`}
              >
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={`${activeTurn.start}-${activeTurn.speaker}`}
                    initial={{
                      opacity: 0,
                      x: agentSpeaking ? -18 : 18,
                      y: 7,
                      scale: 0.97,
                    }}
                    animate={{ opacity: 1, x: 0, y: 0, scale: 1 }}
                    exit={{
                      opacity: 0,
                      x: agentSpeaking ? 12 : -12,
                      y: -6,
                      scale: 0.98,
                    }}
                    transition={{ duration: 0.34, ease }}
                    className={`max-w-[88%] border px-4 py-3 shadow-[0_12px_30px_rgba(0,0,0,.12)] sm:px-5 ${agentSpeaking ? "rounded-[20px] rounded-tl-md border-voltage-violet/25 bg-voltage-violet/18 text-white" : "rounded-[20px] rounded-tr-md border-white/60 bg-lavender-field text-midnight-ink"}`}
                  >
                    <div
                      className={`text-[9px] font-bold uppercase tracking-[.13em] ${agentSpeaking ? "text-lavender-mist" : "text-voltage-violet"}`}
                    >
                      {agentSpeaking ? "Ashutosh · AI agent" : "Customer"}
                    </div>
                    <p
                      className={`mt-1.5 text-xs leading-5 sm:text-[13px] ${agentSpeaking ? "text-white/72" : "text-midnight-ink/75"}`}
                    >
                      “{activeTurn.text}”
                    </p>
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>

            <div className="border-t border-white/10 p-5 sm:p-6">
              <div className="flex items-center gap-4">
                <button
                  onClick={togglePlayback}
                  className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-white text-voltage-violet transition-transform hover:scale-105"
                  aria-label={
                    playing ? "Pause conversation" : "Play conversation"
                  }
                >
                  {playing ? (
                    <Pause className="h-4 w-4 fill-current" />
                  ) : (
                    <Play className="ml-0.5 h-4 w-4 fill-current" />
                  )}
                </button>
                <div className="min-w-0 flex-1">
                  <button
                    onClick={seek}
                    className="block h-2 w-full cursor-pointer overflow-hidden rounded-full bg-white/10"
                    aria-label="Seek through conversation"
                  >
                    <motion.span
                      className="block h-full rounded-full bg-lavender-mist"
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 0.1 }}
                    />
                  </button>
                  <div className="mt-2 flex justify-between text-[10px] text-white/35">
                    <span>{formatTime(currentTime)}</span>
                    <span>{formatTime(totalDuration)}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
