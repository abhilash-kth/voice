"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Menu, X } from "lucide-react";
import { ArrowButton, LogoMark } from "./primitives";

const links = [
  ["About", "/about"],
  ["Voices", "/#agents"],
  ["Languages", "/#languages"],
  ["Compliance", "/#compliance"],
  ["Pricing", "/pricing"],
];
export default function Header() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  
  useEffect(() => {
    window.history.scrollRestoration = "manual";
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });

    return () => {
      window.history.scrollRestoration = "auto";
    };
  }, []);
  
  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-4">
      <motion.div
        animate={{
          maxWidth: scrolled ? 1240 : 1440,
          backgroundColor: scrolled
            ? "rgba(255,255,255,.84)"
            : "rgba(255,255,255,.72)",
        }}
        transition={{ duration: 0.35 }}
        className="relative mx-auto flex items-center justify-between overflow-hidden rounded-full border border-white/70 px-4 py-2.5 shadow-[0_12px_50px_rgba(17,24,39,.08)] backdrop-blur-2xl sm:px-4"
      >
        <motion.div
          animate={{ x: ["-120%", "220%"] }}
          transition={{ duration: 8, repeat: Infinity, repeatDelay: 5 }}
          className="pointer-events-none absolute inset-y-0 w-32 skew-x-[-20deg] bg-gradient-to-r from-transparent via-white/60 to-transparent"
        />
        <LogoMark />
        <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 text-sm font-medium text-graphite lg:flex">
          {links.map(([label, id]) => (
            <a
              key={id}
              href={id}
              className="group relative rounded-full px-3 py-2 transition-colors hover:text-voltage-violet"
            >
              {label}
              <span className="absolute inset-x-3 bottom-1 h-px origin-left scale-x-0 bg-voltage-violet transition-transform group-hover:scale-x-100" />
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          <a
            href="/contact"
            className="rounded-full px-4 py-2.5 text-sm font-semibold transition-colors hover:bg-fog"
          >
            Contact sales
          </a>
          <ArrowButton href="/contact">Create your agent</ArrowButton>
        </div>
        <button
          aria-label="Open menu"
          className="grid h-10 w-10 place-items-center rounded-full bg-fog lg:hidden"
          onClick={() => setOpen(!open)}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </motion.div>
      {open && (
        <motion.div
          initial={{ opacity: 0, y: -8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="mx-auto mt-2 max-w-[1440px] rounded-[28px] border border-white/70 bg-white/90 p-3 shadow-xl backdrop-blur-2xl lg:hidden"
        >
          <nav className="flex flex-col gap-1 text-sm font-semibold">
            {links.map(([label, id]) => (
              <a
                key={id}
                href={id}
                onClick={() => setOpen(false)}
                className="rounded-full px-4 py-2.5 hover:bg-fog"
              >
                {label}
              </a>
            ))}
            <a
              href="/contact"
              className="mt-2 rounded-full bg-voltage-violet px-4 py-2.5 text-center text-white"
            >
              Contact sales
            </a>
          </nav>
        </motion.div>
      )}
    </header>
  );
}
