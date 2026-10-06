"use client";

import { motion } from "framer-motion";
import { ArrowRight, Check, Radio } from "lucide-react";
import { ShaderBackground } from "@/components/ui/manu";

export default function VisionAndCta() {
  return (
    <section
      id="final-cta"
      className="px-5 pb-28 pt-16 sm:px-8 sm:pb-36 sm:pt-20"
    >
      <motion.div
        initial={{ opacity: 0, y: 28 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.8 }}
        className="noise relative mx-auto max-w-[1440px] overflow-hidden rounded-[40px] bg-midnight-ink px-6 py-20 text-center text-white sm:px-12 sm:py-28"
      >
        <ShaderBackground className="absolute inset-0 h-full w-full" />
        <div className="absolute inset-0 bg-midnight-ink/35" />
        <motion.div
          animate={{ x: [0, 30, 0], y: [0, 14, 0] }}
          transition={{ duration: 10, repeat: Infinity }}
          className="absolute left-[8%] top-[-30%] h-96 w-96 rounded-full bg-voltage-violet/25 blur-[90px]"
        />
        <motion.div
          animate={{ x: [0, -25, 0] }}
          transition={{ duration: 12, repeat: Infinity }}
          className="absolute bottom-[-55%] right-[5%] h-96 w-96 rounded-full bg-magenta-spark/20 blur-[100px]"
        />
        <div className="relative z-10 mx-auto max-w-[790px]">
          <motion.div
            whileHover={{ rotate: 8, scale: 1.05 }}
            className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-white text-voltage-violet shadow-[0_16px_40px_rgba(95,37,158,.15)]"
          >
            <Radio className="h-6 w-6" />
          </motion.div>
          <h2 className="mt-8 text-[clamp(2.8rem,6vw,4.9rem)] font-semibold leading-[.94] tracking-[-.068em] text-white">
            Your next customer could call today.
          </h2>
          <p className="mx-auto mt-6 max-w-[610px] text-base leading-7 text-white/65 sm:text-lg">
            Create an agent that answers in your business’s voice—or start with
            a premade role.
          </p>
          <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
            <a
              href="#"
              className="group inline-flex min-h-14 items-center justify-center gap-3 rounded-full bg-white px-8 text-sm font-semibold text-midnight-ink transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_18px_40px_rgba(17,24,39,.22)]"
            >
              Create your agent{" "}
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </a>
            <a
              href="#"
              className="inline-flex min-h-14 items-center justify-center rounded-full border border-white/25 bg-white/10 px-8 text-sm font-semibold text-white backdrop-blur transition-all duration-300 hover:border-midnight-ink/40 hover:bg-white"
            >
              Talk to our team
            </a>
          </div>
          <div className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-3 text-xs font-semibold text-white/75">
            {["Inbound + outbound", "Pay by usage", "11+ languages"].map(
              (item) => (
                <span key={item} className="flex items-center gap-2">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-white">
                    <Check className="h-3 w-3 text-voltage-violet" />
                  </span>
                  {item}
                </span>
              ),
            )}
          </div>
        </div>
      </motion.div>
    </section>
  );
}
