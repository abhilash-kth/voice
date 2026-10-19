"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Pause, Play, Radio } from "lucide-react";
import { ShaderBackground } from "@/components/ui/manu";

const ease = [0.22, 1, 0.36, 1] as const;
const agentAudio =
  "https://ik.imagekit.io/qk2ww553c/ai-calling-agent/priya-agent";
const agentTranscript =
  "नमस्ते, मैं प्रिया बोल रही हूँ। Apollo Clinic की तरफ से यह आपको आपकी Upcoming Doctor Appointment याद दिलाने के लिए कॉल है। आपकी Appointment Apollo Clinic में Scheduled है। कृपया अपने Appointment के समय पर Clinic पहुँचना सुनिश्चित करें। अगर आप Appointment रिस्केजूल या कैंसल करना चाहते हैं, तो Apollo Clinic से संपर्क करें। धन्यवाद।";

export default function Hero() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [previewing, setPreviewing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [desktop, setDesktop] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const update = () => setDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const previewVoice = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (previewing) {
      audio.pause();
      setPreviewing(false);
      return;
    }
    try {
      await audio.play();
      setPreviewing(true);
    } catch {
      setPreviewing(false);
    }
  };

  const formatTime = (seconds: number) => {
    if (!Number.isFinite(seconds)) return "0:00";
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${Math.floor(seconds % 60)
      .toString()
      .padStart(2, "0")}`;
  };
  return (
    <section id="top" className="px-4 pb-14 pt-22 sm:px-6 sm:pb-16 sm:pt-24">
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.9, ease }}
        className="noise relative isolate mx-auto min-h-[590px] max-w-[1440px] overflow-hidden rounded-[36px] bg-[#160925] px-7 pb-7 pt-12 text-white shadow-[0_40px_120px_rgba(71,28,120,.22)] [clip-path:inset(0_round_36px)] sm:rounded-[48px] sm:px-10 sm:pb-10 sm:pt-14 sm:[clip-path:inset(0_round_48px)]"
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
          layout
          initial={{ opacity: 0, y: 38, maxWidth: 360, height: 76 }}
          animate={{
            opacity: 1,
            y: 0,
            maxWidth: previewing ? 1440 : 360,
            height: previewing ? (desktop ? 140 : 300) : 76,
          }}
          transition={{
            opacity: { delay: 0.65, duration: 0.9, ease },
            y: { delay: 0.65, duration: 0.9, ease },
            maxWidth: {
              type: "spring",
              stiffness: 115,
              damping: 24,
              mass: 0.9,
            },
            height: { duration: 0.68, ease },
            layout: { type: "spring", stiffness: 150, damping: 25 },
          }}
          className="relative z-10 mx-auto mt-8 w-full overflow-hidden rounded-[26px] border border-white/[.12] bg-[radial-gradient(circle_at_18%_-20%,rgba(255,255,255,.16),transparent_42%),linear-gradient(145deg,rgba(255,255,255,.10)_0%,rgba(255,255,255,.035)_48%,rgba(105,52,153,.09)_100%)] shadow-[0_24px_70px_rgba(4,0,12,.24),inset_0_1px_0_rgba(255,255,255,.22),inset_0_-1px_0_rgba(0,0,0,.16)] backdrop-blur-[12px] backdrop-saturate-125 [-webkit-backdrop-filter:blur(12px)_saturate(1.25)] before:pointer-events-none before:absolute before:inset-0 before:rounded-[inherit] before:bg-[linear-gradient(115deg,rgba(255,255,255,.10),transparent_28%,transparent_72%,rgba(255,255,255,.025))]"
        >
          <audio
            ref={audioRef}
            src={agentAudio}
            preload="metadata"
            onLoadedMetadata={(event) =>
              setDuration(event.currentTarget.duration)
            }
            onTimeUpdate={(event) =>
              setProgress(
                event.currentTarget.duration
                  ? (event.currentTarget.currentTime /
                      event.currentTarget.duration) *
                      100
                  : 0,
              )
            }
            onEnded={() => {
              setPreviewing(false);
              setProgress(0);
            }}
          />

          <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-lavender-mist/14 blur-[80px]" />
          <motion.div
            layout
            transition={{
              layout: { type: "spring", stiffness: 200, damping: 27 },
            }}
            className="relative"
          >
            <AnimatePresence mode="popLayout" initial={false}>
              {!previewing ? (
                <motion.div
                  key="collapsed-agent"
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4, filter: "blur(3px)" }}
                  transition={{ duration: 0.26, ease }}
                  className="flex h-[76px] items-center gap-3 px-5 py-3"
                >
                  <span className="relative size-12 min-h-12 min-w-12 shrink-0 overflow-hidden rounded-full border border-white/20 bg-lavender-field [clip-path:circle(50%)]">
                    <Image
                      src="/images/voices/aanya-pro.jpg"
                      alt="Priya voice agent"
                      fill
                      className="object-cover object-top"
                      sizes="48px"
                    />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold tracking-[-.03em]">
                        Priya
                      </h3>
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    </div>
                    <div className="mt-1 truncate text-[11px] text-white/60">
                      Hindi · Indian accent
                    </div>
                  </div>
                  <button
                    onClick={previewVoice}
                    className="grid h-12 w-12 shrink-0 cursor-pointer place-items-center rounded-full bg-white text-voltage-violet shadow-[0_10px_26px_rgba(0,0,0,.18)] transition-transform hover:scale-105"
                    aria-label="Play Priya's recording"
                  >
                    <Play className="ml-0.5 h-[17px] w-[17px] fill-current" />
                  </button>
                </motion.div>
              ) : (
                <motion.div
                  key="expanded-agent"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 5 }}
                  transition={{ duration: 0.38, delay: 0.12, ease }}
                  className="relative grid h-full lg:grid-cols-[.34fr_.66fr]"
                >
                  <motion.div
                    animate={{
                      opacity: [0.12, 0.3, 0.12],
                      scale: [0.9, 1.1, 0.9],
                    }}
                    transition={{
                      duration: 2.2,
                      repeat: Infinity,
                      ease: "easeInOut",
                    }}
                    className="pointer-events-none absolute -bottom-20 -left-16 h-52 w-52 rounded-full bg-voltage-violet/35 blur-[60px]"
                  />
                  <div className="relative flex flex-col justify-between border-b border-white/10 p-4 lg:border-b-0 lg:border-r">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span className="relative size-9 min-h-9 min-w-9 shrink-0 overflow-hidden rounded-full border border-white/20 bg-lavender-field [clip-path:circle(50%)]">
                          <Image
                            src="/images/voices/aanya-pro.jpg"
                            alt="Priya voice agent"
                            fill
                            className="object-cover object-top"
                            sizes="36px"
                          />
                        </span>
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-lg font-semibold tracking-[-.035em]">
                              Priya
                            </h3>
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                          </div>
                          <div className="mt-0.5 text-[10px] text-white/60">
                            Hindi · Indian accent
                          </div>
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full border border-white/12 bg-white/[.08] px-2.5 py-1.5 text-[10px] font-semibold text-white/60">
                        Appointment agent
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={previewVoice}
                        className="grid h-10 w-10 shrink-0 cursor-pointer place-items-center rounded-full bg-white text-voltage-violet shadow-[0_10px_24px_rgba(0,0,0,.16)] transition-transform hover:scale-105"
                        aria-label="Pause Priya's recording"
                      >
                        <Pause className="h-3.5 w-3.5 fill-current" />
                      </button>
                      <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/10">
                        <motion.div
                          className="h-full rounded-full bg-lavender-mist"
                          animate={{ width: `${progress}%` }}
                          transition={{ duration: 0.1 }}
                        />
                      </div>
                      <span className="w-8 text-right text-[10px] font-semibold text-white/40">
                        {formatTime(duration)}
                      </span>
                    </div>
                  </div>
                  <motion.div
                    initial={{ opacity: 0, x: 24, filter: "blur(4px)" }}
                    animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
                    transition={{ duration: 0.4, delay: 0.18, ease }}
                    className="flex flex-col justify-center p-4 lg:p-5 lg:pl-7"
                  >
                    <div className="text-[9px] font-bold uppercase tracking-[.16em] text-lavender-mist">
                      Call transcript
                    </div>
                    <p className="mt-2 max-w-[900px] text-[11px] leading-[1.55] text-white/70 sm:text-[12px]">
                      “{agentTranscript}”
                    </p>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      </motion.div>
    </section>
  );
}
