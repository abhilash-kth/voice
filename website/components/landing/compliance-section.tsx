"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowRight, BadgeCheck } from "lucide-react";

const credentials = [
  {
    title: "CMMI Level 3",
    text: "Defined and managed delivery processes.",
    image: "/images/compliance/cmmi.png",
  },
  {
    title: "ISO registered",
    text: "Registered standards and operating controls.",
    image: "/images/compliance/iso.webp",
  },
  {
    title: "CE certified",
    text: "Conformity credential for applicable requirements.",
    image: "/images/compliance/ce.webp",
  },
];

export default function ComplianceSection() {
  return (
    <section id="compliance" className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <motion.div
        initial={{ opacity: 0, y: 28 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        className="relative mx-auto max-w-[1440px] overflow-hidden rounded-[42px] border border-[#edc950]/55 bg-[linear-gradient(135deg,#fffdf5_0%,#fff4c9_48%,#ffe39a_100%)] p-7 text-[#332407] shadow-[0_34px_90px_rgba(194,140,9,.16)] sm:p-12 lg:p-14"
      >
        <motion.div
          animate={{ x: ["-120%", "230%"] }}
          transition={{
            duration: 4.5,
            repeat: Infinity,
            repeatDelay: 2.5,
            ease: "easeInOut",
          }}
          className="pointer-events-none absolute inset-y-0 w-52 skew-x-[-18deg] bg-gradient-to-r from-transparent via-white/70 to-transparent blur-xl"
        />
        <div className="absolute -left-20 -top-32 h-96 w-96 rounded-full bg-[#ffd84f]/35 blur-[90px]" />
        <div className="absolute -bottom-36 right-[-3%] h-96 w-96 rounded-full bg-[#ffbe1a]/24 blur-[90px]" />
        <div className="relative grid gap-12 lg:grid-cols-[.9fr_1.1fr] lg:items-center">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#d6a817]/30 bg-white/65 px-4 py-2 text-xs font-bold text-[#8a6200]">
              <BadgeCheck className="h-3.5 w-3.5" />
              Verified foundation
            </div>
            <h2 className="mt-6 max-w-[690px] text-[clamp(2.7rem,5vw,4.7rem)] font-semibold leading-[.95] tracking-[-.065em]">
              Trust, <span className="text-yellow-500">Verified</span> before the first call.
            </h2>
            <p className="mt-5 max-w-[570px] text-base leading-7 text-[#6e551d]">
              Recognized credentials and DLT registration give businesses a
              stronger foundation for accountable AI calling.
            </p>
            <a
              href="#final-cta"
              className="group mt-8 inline-flex min-h-12 items-center gap-3 rounded-full bg-[#2b210a] px-6 text-sm font-semibold text-white transition-all hover:-translate-y-1 hover:shadow-[0_16px_35px_rgba(79,55,4,.22)]"
            >
              Contact sales{" "}
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </a>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid grid-cols-3 gap-3 sm:col-span-2">
              {credentials.map((item, index) => (
                <motion.div
                  initial={{ opacity: 0, y: 18 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.08 }}
                  whileHover={{ y: -5 }}
                  key={item.title}
                  className="rounded-[24px] border border-[#d7ad31]/30 bg-white/72 p-4 text-center shadow-[0_14px_35px_rgba(143,99,0,.08)] backdrop-blur"
                >
                  <div className="relative mx-auto h-16 w-16">
                    <Image
                      src={item.image}
                      alt={item.title}
                      fill
                      className="object-contain"
                      sizes="64px"
                    />
                  </div>
                  <h3 className="mt-3 text-sm font-bold">{item.title}</h3>
                  <p className="mt-1 hidden text-xs leading-5 text-[#80672b] md:block">
                    {item.text}
                  </p>
                </motion.div>
              ))}
            </div>
            <motion.div
              whileHover={{ y: -4 }}
              className="sm:col-span-2 flex items-center justify-between rounded-[24px] border border-[#d7ad31]/35 bg-[#2b210a] p-5 text-white"
            >
              <div className="flex items-center gap-4">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-[#f5c62b] text-[#2b210a]">
                  <BadgeCheck className="h-5 w-5" />
                </span>
                <div>
                  <div className="text-base font-semibold">DLT registered</div>
                  <div className="mt-1 text-xs text-white/55">
                    Registered foundation for business calling in India.
                  </div>
                </div>
              </div>
              <span className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold text-[#ffe58d]">
                Active
              </span>
            </motion.div>
          </div>
        </div>
      </motion.div>
    </section>
  );
}
