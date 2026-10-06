"use client";

import { motion } from "framer-motion";
import {
  ArrowRight,
  AudioLines,
  Building2,
  Code2,
  Languages,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

const principles = [
  {
    icon: AudioLines,
    title: "Natural by design",
    text: "Build conversations around listening, interruption, context, and clear responses—not rigid phone trees.",
  },
  {
    icon: SlidersHorizontal,
    title: "Simple to operate",
    text: "Give business teams a direct path from describing a role to reviewing and running an agent.",
  },
  {
    icon: Languages,
    title: "Made for multilingual calls",
    text: "Support conversations across Indian languages without treating language as an afterthought.",
  },
  {
    icon: ShieldCheck,
    title: "Trust must be visible",
    text: "Make costs, controls, call records, and compliance information understandable to the teams using them.",
  },
];
const companyPoints = [
  {
    icon: Building2,
    title: "Established in 2014",
    text: "Kriscent Techno Hub Pvt Ltd is based in Kota, Rajasthan, and serves businesses in India and globally.",
  },
  {
    icon: Code2,
    title: "End-to-end technology capability",
    text: "Its work spans custom software, web and mobile development, digital solutions, and scalable business systems.",
  },
  {
    icon: Sparkles,
    title: "Experience with emerging technology",
    text: "Kriscent’s technology practice includes AI and other emerging solutions built around specific business requirements.",
  },
];

export default function AboutPageContent() {
  return (
    <main id="top" className="bg-white text-midnight-ink">
      <Header />
      <section className="relative overflow-hidden px-5 pb-20 pt-36 sm:px-8 lg:pt-44">
        <div className="absolute left-1/2 top-20 h-[480px] w-[760px] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(196,154,255,.36),rgba(255,222,177,.17)_45%,transparent_72%)] blur-2xl" />
        <div className="relative mx-auto max-w-[1440px]">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            className="mx-auto max-w-[960px] text-center"
          >
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              About Voxura
            </div>
            <h1 className="mt-6 text-[clamp(3.7rem,8vw,7.5rem)] font-semibold leading-[.88] tracking-[-.075em]">
              A voice workforce businesses can actually operate.
            </h1>
            <p className="mx-auto mt-8 max-w-[720px] text-lg leading-8 text-slate">
              Voxura is a self-serve AI voice-agent product for inbound and
              outbound business calls. It brings agent creation, voices,
              languages, models, usage, and call activity into one focused
              workspace.
            </p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            className="relative mt-16 overflow-hidden rounded-[42px] bg-midnight-ink p-7 text-white sm:p-12 lg:p-14"
          >
            <div className="absolute -right-28 -top-32 h-96 w-96 rounded-full bg-voltage-violet/35 blur-[90px]" />
            <div className="relative grid gap-10 lg:grid-cols-[.85fr_1.15fr] lg:items-end">
              <div>
                <div className="text-xs font-bold uppercase tracking-[.14em] text-lavender-mist">
                  Why we’re building it
                </div>
                <h2 className="mt-5 text-[clamp(2.7rem,5vw,4.8rem)] font-semibold leading-[.96] tracking-[-.06em]">
                  Business calls need a better operating layer.
                </h2>
              </div>
              <p className="max-w-[620px] text-base leading-8 text-white/60">
                Phone conversations still carry important customer intent, but
                traditional automation often makes them harder. Voxura is being
                designed to let teams define the work clearly, choose how the
                agent sounds, understand what it costs, and improve it from real
                conversations.
              </p>
            </div>
          </motion.div>
        </div>
      </section>

      <section className="px-5 py-16 sm:px-8 lg:py-24">
        <div className="mx-auto max-w-[1440px]">
          <div className="grid gap-10 lg:grid-cols-[.78fr_1.22fr] lg:items-end">
            <div>
              <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
                The company behind Voxura
              </div>
              <h2 className="mt-5 text-[clamp(2.8rem,5vw,4.7rem)] font-semibold leading-[.97] tracking-[-.06em]">
                Developed by Kriscent Techno Hub.
              </h2>
            </div>
            <div>
              <p className="max-w-[680px] text-base leading-8 text-slate">
                Voxura is being developed by Kriscent Techno Hub Pvt Ltd, a
                technology company focused on building tailored, scalable
                solutions for business needs. The product combines Kriscent’s
                software-delivery experience with a focused approach to
                practical AI voice operations.
              </p>
              <a
                href="https://kriscent.in/about/"
                target="_blank"
                rel="noreferrer"
                className="group mt-5 inline-flex items-center gap-2 text-sm font-semibold text-voltage-violet"
              >
                Visit Kriscent Techno Hub{" "}
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </a>
            </div>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {companyPoints.map((item, index) => {
              const Icon = item.icon;
              return (
                <motion.article
                  initial={{ opacity: 0, y: 18 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.07 }}
                  key={item.title}
                  className="rounded-[28px] border border-mist bg-fog/45 p-7"
                >
                  <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white text-voltage-violet shadow-subtle">
                    <Icon className="h-5 w-5" />
                  </span>
                  <h3 className="mt-7 text-lg font-semibold">{item.title}</h3>
                  <p className="mt-3 text-sm leading-7 text-slate">
                    {item.text}
                  </p>
                </motion.article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="px-5 py-16 sm:px-8 lg:py-24">
        <div className="mx-auto max-w-[1440px]">
          <div className="max-w-[700px]">
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Product principles
            </div>
            <h2 className="mt-5 text-[clamp(2.8rem,5vw,4.7rem)] font-semibold leading-[.97] tracking-[-.06em]">
              Clear choices. Useful conversations.
            </h2>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {principles.map((item, index) => {
              const Icon = item.icon;
              return (
                <motion.article
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.06 }}
                  whileHover={{ y: -5 }}
                  key={item.title}
                  className="rounded-[30px] border border-mist bg-fog/45 p-7 sm:p-8"
                >
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-voltage-violet shadow-subtle">
                    <Icon className="h-5 w-5" />
                  </span>
                  <h3 className="mt-8 text-xl font-semibold">{item.title}</h3>
                  <p className="mt-3 max-w-[520px] text-sm leading-7 text-slate">
                    {item.text}
                  </p>
                </motion.article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="px-5 py-16 sm:px-8">
        <div className="mx-auto flex max-w-[1440px] flex-col items-start justify-between gap-8 rounded-[38px] bg-lavender-field p-8 sm:p-12 lg:flex-row lg:items-end">
          <div>
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Build with us
            </div>
            <h2 className="mt-4 max-w-[760px] text-[clamp(2.5rem,5vw,4.2rem)] font-semibold leading-[1] tracking-[-.055em]">
              Tell us which calls your business needs to handle.
            </h2>
          </div>
          <a
            href="/contact"
            className="group inline-flex min-h-12 shrink-0 items-center gap-3 rounded-full bg-voltage-violet px-6 text-sm font-semibold text-white"
          >
            Contact us{" "}
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </a>
        </div>
      </section>
      <Footer />
    </main>
  );
}
