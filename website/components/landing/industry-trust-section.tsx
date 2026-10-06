"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import { BriefcaseBusiness, Building2, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { Eyebrow } from "./primitives";

const ASSETS_BASE_URL = "https://ik.imagekit.io/qk2ww553c";
const clientLogos = [
  {
    name: "Shree Falodi Finance",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/shree-falodi.png`,
  },
  {
    name: "HR Walla",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/hr.png`,
  },
  {
    name: "RGCSM",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/rgcsm.png`,
  },
  {
    name: "Chabi Digital Solutions",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/chabi-updated.webp`,
  },
  {
    name: "Kamal Fincap",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/kamal.png`,
  },
  {
    name: "Shree Shree Micro serve Foundation",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/msf.png`,
  },
  {
    name: "TSBOS",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/tsbos.webp`,
  },
  {
    name: "Divine Touch",
    logo: `${ASSETS_BASE_URL}/tempAssets/clientsImages/divinetouch.webp`,
  },
];

export default function IndustryTrustSection() {
  const [industry, setIndustry] = useState<"bfsi" | "it">("bfsi");
  const data = {
    bfsi: {
      label: "BFSI",
      title: "Careful conversations for financial services.",
      roles: ["Finance assistance", "Customer support", "Reception"],
      icon: Building2,
    },
    it: {
      label: "IT & technology",
      title: "Voice capacity for teams that move fast.",
      roles: ["HR assistance", "Sales qualification", "Customer support"],
      icon: BriefcaseBusiness,
    },
  }[industry];
  const Icon = data.icon;
  return (
    <section className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto max-w-[1440px]">
        <div className="grid gap-5 lg:grid-cols-[1.12fr_.88fr]">
          <div className="overflow-hidden rounded-[36px] bg-fog p-7 sm:p-10">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
              <Eyebrow className="mb-0">Business roles</Eyebrow>
              <div className="flex rounded-full bg-white p-1.5 shadow-sm">
                <button
                  onClick={() => setIndustry("bfsi")}
                  className={cn(
                    "rounded-full px-4 py-2 text-xs font-semibold transition-colors",
                    industry === "bfsi"
                      ? "bg-midnight-ink text-white"
                      : "text-slate",
                  )}
                >
                  BFSI
                </button>
                <button
                  onClick={() => setIndustry("it")}
                  className={cn(
                    "rounded-full px-4 py-2 text-xs font-semibold transition-colors",
                    industry === "it"
                      ? "bg-midnight-ink text-white"
                      : "text-slate",
                  )}
                >
                  IT & technology
                </button>
              </div>
            </div>
            <motion.div
              key={industry}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-14 grid gap-10 md:grid-cols-[1fr_.75fr] md:items-end"
            >
              <div>
                <span className="grid h-14 w-14 place-items-center rounded-2xl bg-lavender-field text-voltage-violet">
                  <Icon className="h-6 w-6" />
                </span>
                <h3 className="mt-7 max-w-[550px] text-[clamp(2.5rem,4vw,3.8rem)] font-semibold leading-[1.04] tracking-[-.05em]">
                  {data.title}
                </h3>
              </div>
              <div className="space-y-2">
                {data.roles.map((role, i) => (
                  <div
                    key={role}
                    className="flex items-center justify-between rounded-2xl bg-white p-4 text-sm font-semibold"
                  >
                    <span>{role}</span>
                    <span className="text-xs text-slate">0{i + 1}</span>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>
          <div className="flex flex-col justify-between rounded-[36px] bg-lavender-field p-7 sm:p-10">
            <div className="flex items-start justify-between">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white">
                <ShieldCheck className="h-5 w-5 text-voltage-violet" />
              </span>
              <span className="rounded-full border border-midnight-ink/10 bg-white/50 px-3 py-1.5 text-xs font-semibold">
                DLT registered
              </span>
            </div>
            <div className="py-14">
              <div className="text-[clamp(4.5rem,9vw,7rem)] font-semibold leading-none tracking-[-.08em] text-voltage-violet">
                40+
              </div>
              <h3 className="mt-3 text-2xl font-semibold tracking-[-.035em]">
                businesses building with Voxura
              </h3>
              <p className="mt-4 max-w-[400px] text-sm leading-6 text-graphite">
                Built for real business calls, with stored conversations and DLT
                registration as part of the operating foundation.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {["Inbound", "Outbound", "11+ languages", "Stored calls"].map(
                (item) => (
                  <span
                    key={item}
                    className="rounded-full bg-white/60 px-3 py-2 text-xs font-semibold text-graphite"
                  >
                    {item}
                  </span>
                ),
              )}
            </div>
          </div>
        </div>
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mt-5 rounded-[28px] border border-mist bg-white px-6 py-6 sm:px-8"
        >
          <div className="mb-5 text-[10px] font-bold uppercase tracking-[.16em] text-slate">
            Selected clients
          </div>
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4 lg:grid-cols-8">
            {clientLogos.map((client) => (
              <motion.div
                whileHover={{ y: -3 }}
                transition={{ duration: 0.2 }}
                key={client.name}
                className="flex h-12 items-center justify-center px-2"
              >
                <img
                  src={client.logo}
                  alt={client.name}
                  loading="lazy"
                  className="max-h-10 max-w-full object-contain"
                />
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
}
