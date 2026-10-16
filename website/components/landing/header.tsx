"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUpRight,
  AudioLines,
  BadgeIndianRupee,
  Languages,
  Menu,
  MessageCircle,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { ArrowButton, LogoMark } from "./primitives";

const links = [
  { label: "About", href: "/about", icon: UserRound },
  { label: "Voices", href: "/#agents", icon: AudioLines },
  { label: "Languages", href: "/#languages", icon: Languages },
  { label: "Compliance", href: "/#compliance", icon: ShieldCheck },
  { label: "Pricing", href: "/pricing", icon: BadgeIndianRupee },
];

const menuVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.07, delayChildren: 0.12 },
  },
};

const linkVariants = {
  hidden: { opacity: 0, x: -18, y: 8 },
  visible: {
    opacity: 1,
    x: 0,
    y: 0,
    transition: { duration: 0.42, ease: [0.22, 1, 0.36, 1] as const },
  },
};

export default function Header() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    window.history.scrollRestoration = "manual";
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });

    const handleScroll = () => setScrolled(window.scrollY > 20);
    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });

    return () => {
      window.history.scrollRestoration = "auto";
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-4">
      <motion.div
        animate={{
          maxWidth: scrolled ? 1240 : 1440,
          backgroundColor: open
            ? "rgba(255,255,255,.94)"
            : scrolled
              ? "rgba(255,255,255,.84)"
              : "rgba(255,255,255,.72)",
        }}
        transition={{ duration: 0.35 }}
        className="relative z-50 mx-auto flex items-center justify-between overflow-hidden rounded-full border border-white/70 px-4 py-2.5 shadow-[0_12px_50px_rgba(17,24,39,.18)] backdrop-blur-2xl"
      >
        <motion.div
          animate={{ x: ["-120%", "220%"] }}
          transition={{ duration: 8, repeat: Infinity, repeatDelay: 5 }}
          className="pointer-events-none absolute inset-y-0 w-32 skew-x-[-20deg] bg-gradient-to-r from-transparent via-white/60 to-transparent"
        />

        <LogoMark />

        <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-0.5 text-sm font-medium text-graphite lg:flex">
          {links.map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.href}
                href={item.href}
                className="group relative flex items-center gap-1.5 rounded-full px-3 py-2 transition-all hover:bg-fog hover:text-voltage-violet text-base"
              >
                <Icon className="h-4 w-4 text-primary transition-colors group-hover:text-voltage-violet" />
                {item.label}
              </a>
            );
          })}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <a
            href="/contact"
            className="rounded-full px-4 py-2.5 text-base font-semibold transition-colors hover:bg-fog"
          >
            Contact sales
          </a>
          <ArrowButton href="/contact">Create your agent</ArrowButton>
        </div>

        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          className="relative grid h-10 w-10 place-items-center overflow-hidden rounded-full bg-midnight-ink text-white shadow-[0_8px_22px_rgba(17,24,39,.18)] lg:hidden"
          onClick={() => setOpen((value) => !value)}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={open ? "close" : "menu"}
              initial={{ opacity: 0, rotate: -55, scale: 0.7 }}
              animate={{ opacity: 1, rotate: 0, scale: 1 }}
              exit={{ opacity: 0, rotate: 55, scale: 0.7 }}
              transition={{ duration: 0.2 }}
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </motion.span>
          </AnimatePresence>
        </button>
      </motion.div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{
              opacity: 0,
              clipPath: "circle(0% at calc(100% - 38px) 34px)",
            }}
            animate={{
              opacity: 1,
              clipPath: "circle(150% at calc(100% - 38px) 34px)",
            }}
            exit={{
              opacity: 0,
              clipPath: "circle(0% at calc(100% - 38px) 34px)",
            }}
            transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            className="fixed inset-0 z-40 overflow-x-hidden overflow-y-auto bg-[#f8f5fc] px-5 pb-6 pt-24 lg:hidden"
          >
            <div className="pointer-events-none absolute -right-28 -top-20 h-96 w-96 rounded-full bg-lavender-field blur-[100px]" />
            <div className="pointer-events-none absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-amber-100/60 blur-[110px]" />
            <div className="pointer-events-none absolute inset-0 opacity-[.35] [background-image:radial-gradient(rgba(134,47,231,.16)_1px,transparent_1px)] [background-size:20px_20px]" />

            <motion.div
              variants={menuVariants}
              initial="hidden"
              animate="visible"
              className="relative mx-auto flex h-full max-w-[700px] flex-col"
            >
              <motion.div
                variants={linkVariants}
                className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.16em] text-voltage-violet"
              >
                <Sparkles className="h-3.5 w-3.5" /> Explore Voxura
              </motion.div>

              <nav className="mt-5 space-y-2">
                {links.map((item, index) => {
                  const Icon = item.icon;
                  return (
                    <motion.a
                      variants={linkVariants}
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      className="group flex min-h-[66px] items-center rounded-[22px] border border-white/80 bg-white/65 px-3.5 shadow-[0_10px_35px_rgba(58,34,82,.05)] backdrop-blur-xl transition-colors hover:bg-white"
                    >
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-lavender-field text-voltage-violet transition-transform group-hover:scale-105">
                        <Icon className="h-5 w-5" />
                      </span>
                      <span className="ml-4 flex-1 text-[clamp(1.15rem,5vw,1.45rem)] font-semibold tracking-[-.035em] text-midnight-ink">
                        {item.label}
                      </span>
                      <span className="mr-3 text-[10px] font-semibold text-slate">
                        0{index + 1}
                      </span>
                      <ArrowUpRight className="h-4 w-4 text-slate transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-voltage-violet" />
                    </motion.a>
                  );
                })}
              </nav>

              <motion.div
                variants={linkVariants}
                className="mt-3 rounded-[28px] bg-midnight-ink p-5 text-white shadow-[0_24px_60px_rgba(25,11,42,.2)]"
              >
                <div className="flex items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-white/10 text-lavender-mist">
                    <MessageCircle className="h-4 w-4" />
                  </span>
                  <div>
                    <div className="text-sm font-semibold">
                      Ready to plan your voice agent?
                    </div>
                    <p className="mt-1 text-xs leading-5 text-white/50">
                      Tell us which calls your business needs to handle.
                    </p>
                  </div>
                </div>
                <div className="mt-5 grid grid-cols-2 gap-2">
                  <a
                    href="/contact"
                    onClick={() => setOpen(false)}
                    className="inline-flex min-h-12 items-center justify-center rounded-full border border-white/15 bg-white/[.06] px-4 text-xs font-semibold text-white"
                  >
                    Contact sales
                  </a>
                  <a
                    href="/contact"
                    onClick={() => setOpen(false)}
                    className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-white px-4 text-xs font-semibold text-midnight-ink"
                  >
                    Create an agent <ArrowUpRight className="h-3.5 w-3.5" />
                  </a>
                </div>
              </motion.div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
