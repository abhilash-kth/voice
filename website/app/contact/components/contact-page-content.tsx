"use client";

import { motion } from "framer-motion";
import {
  ArrowUpRight,
  Building2,
  Globe2,
  Mail,
  MessageSquare,
  PhoneCall,
} from "lucide-react";
import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

const contactDetails = [
  {
    icon: Mail,
    label: "Email",
    value: "info@kriscent.in",
    href: "mailto:info@kriscent.in",
  },
  {
    icon: PhoneCall,
    label: "Call",
    value: "+91 89470 27625",
    href: "tel:+918947027625",
  },
  {
    icon: MessageSquare,
    label: "WhatsApp",
    value: "+91 89470 27625",
    href: "https://wa.me/918947027625",
  },
  {
    icon: Building2,
    label: "Company",
    value: "Kriscent Techno Hub Pvt Ltd",
    href: "https://kriscent.in/",
  },
];

const emailChecklist = [
  "The calls you want the agent to handle",
  "Inbound, outbound, or both",
  "Preferred languages and expected call volume",
];

export default function ContactPageContent() {
  return (
    <main id="top" className="min-h-screen bg-white text-midnight-ink">
      <Header />
      <section className="relative overflow-hidden px-5 pb-16 pt-36 sm:px-8 lg:pb-24 lg:pt-44">
        <div className="absolute left-[8%] top-20 h-72 w-72 rounded-full bg-lavender-field/70 blur-[90px]" />
        <div className="absolute right-[5%] top-36 h-80 w-80 rounded-full bg-amber-100/55 blur-[100px]" />

        <div className="relative mx-auto grid max-w-[1440px] gap-12 lg:grid-cols-[.82fr_1.18fr] lg:items-start">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Contact our team
            </div>
            <h1 className="mt-5 max-w-[650px] text-[clamp(3.5rem,7vw,6.8rem)] font-semibold leading-[.9] tracking-[-.07em]">
              Let’s plan your voice agent.
            </h1>
            <p className="mt-7 max-w-[560px] text-lg leading-8 text-slate">
              Share what your business needs to handle. We can discuss the role,
              languages, call flow, and the right setup for your team.
            </p>

            <div className="mt-10 flex flex-wrap gap-2">
              {["Inbound calls", "Outbound calls", "Multilingual agents"].map(
                (item) => (
                  <span
                    key={item}
                    className="rounded-full border border-mist bg-white/75 px-4 py-2 text-xs font-semibold text-graphite backdrop-blur"
                  >
                    {item}
                  </span>
                ),
              )}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
            className="relative overflow-hidden rounded-[38px] bg-midnight-ink p-6 text-white shadow-[0_28px_80px_rgba(38,17,59,.18)] sm:p-9"
          >
            <div className="absolute -right-24 -top-28 h-80 w-80 rounded-full bg-voltage-violet/35 blur-[85px]" />
            <div className="absolute -bottom-28 left-[12%] h-72 w-72 rounded-full bg-[#b95cff]/15 blur-[90px]" />
            <div className="absolute inset-0 opacity-[.04] [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:18px_18px]" />

            <div className="relative">
              <div className="flex items-start justify-between gap-5">
                <div className="flex items-center gap-3">
                  <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white/10 text-lavender-mist">
                    <MessageSquare className="h-5 w-5" />
                  </span>
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-[.15em] text-white/40">
                      Start a conversation
                    </div>
                    <h2 className="mt-1 text-xl font-semibold">
                      Contact details
                    </h2>
                  </div>
                </div>
                <Globe2 className="hidden h-5 w-5 text-white/25 sm:block" />
              </div>

              <div className="mt-8 space-y-2">
                {contactDetails.map((detail) => {
                  const Icon = detail.icon;
                  const content = (
                    <>
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-white/[.07] text-lavender-mist">
                        <Icon className="h-4.5 w-4.5" />
                      </span>
                      <span className="ml-4 min-w-0 flex-1">
                        <span className="block text-[10px] font-bold uppercase tracking-[.13em] text-white/35">
                          {detail.label}
                        </span>
                        <span className="mt-1 block text-sm font-semibold leading-5 text-white">
                          {detail.value}
                        </span>
                      </span>
                      {detail.href && (
                        <ArrowUpRight className="h-4 w-4 text-white/30 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-lavender-mist" />
                      )}
                    </>
                  );

                  return detail.href ? (
                    <a
                      key={detail.label}
                      href={detail.href}
                      target={
                        detail.href.startsWith("http") ? "_blank" : undefined
                      }
                      rel={
                        detail.href.startsWith("http")
                          ? "noreferrer"
                          : undefined
                      }
                      className="group flex items-center rounded-[22px] border border-white/[.07] bg-white/[.045] p-3 transition-colors hover:bg-white/[.08]"
                    >
                      {content}
                    </a>
                  ) : (
                    <div
                      key={detail.label}
                      className="flex items-center rounded-[22px] border border-white/[.07] bg-white/[.045] p-3"
                    >
                      {content}
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        </div>
      </section>
      <Footer />
    </main>
  );
}
