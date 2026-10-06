"use client";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BadgeIndianRupee,
  Check,
  CircleAlert,
  PhoneCall,
  WalletCards,
} from "lucide-react";
import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

const included = [
  "Create and configure voice agents",
  "Inbound and outbound calling",
  "Voice and language selection",
  "Call history and usage visibility",
  "One selected AI model per agent",
];
const layers = [
  {
    title: "Voice-agent usage",
    text: "The core per-minute platform charge for running the agent.",
  },
  {
    title: "Selected AI model",
    text: "Model cost can vary based on the model assigned to the agent.",
  },
  {
    title: "Telephony",
    text: "Phone-number and carrier costs can vary by destination and provider.",
  },
];
export default function PricingPageContent() {
  return (
    <main id="top" className="bg-white text-midnight-ink">
      <Header />
      <section className="relative overflow-hidden px-5 pb-16 pt-36 sm:px-8 lg:pt-44">
        <div className="absolute left-[12%] top-24 h-80 w-80 rounded-full bg-lavender-field blur-[100px]" />
        <div className="absolute right-[9%] top-28 h-72 w-72 rounded-full bg-amber-100/60 blur-[100px]" />
        <div className="relative mx-auto max-w-[1440px]">
          <motion.div
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            className="mx-auto max-w-[850px] text-center"
          >
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Pricing
            </div>
            <h1 className="mt-6 text-[clamp(3.7rem,8vw,7.2rem)] font-semibold leading-[.88] tracking-[-.075em]">
              Fund the wallet. Pay as calls run.
            </h1>
            <p className="mx-auto mt-8 max-w-[690px] text-lg leading-8 text-slate">
              We are currently shaping the final commercial plans. This page
              presents the proposed usage-based structure for internal
              review—not a final price commitment.
            </p>
          </motion.div>
          <div className="mx-auto mt-14 grid max-w-[1120px] gap-4 lg:grid-cols-[1.08fr_.92fr]">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="relative overflow-hidden rounded-[38px] bg-voltage-violet p-8 text-white sm:p-10"
            >
              <div className="absolute -right-20 -top-20 h-72 w-72 rounded-full bg-lavender-mist/30 blur-[70px]" />
              <div className="relative">
                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white/15">
                  <WalletCards className="h-5 w-5" />
                </span>
                <div className="mt-9 text-sm font-semibold text-lavender-mist">
                  Proposed wallet model
                </div>
                <h2 className="mt-3 text-[clamp(2.5rem,5vw,4.5rem)] font-semibold leading-[.95] tracking-[-.06em]">
                  Usage stays visible as it happens.
                </h2>
                <p className="mt-5 max-w-[560px] text-sm leading-7 text-white/65">
                  Add funds to a business wallet, see the applicable call rate,
                  and review the deduction after each completed call.
                </p>
                <a
                  href="/contact"
                  className="group mt-8 inline-flex min-h-12 items-center gap-3 rounded-full bg-white px-6 text-sm font-semibold text-voltage-violet"
                >
                  Discuss pricing{" "}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </a>
              </div>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="rounded-[38px] border border-mist bg-white p-8 sm:p-10"
            >
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-fog text-voltage-violet">
                  <BadgeIndianRupee className="h-5 w-5" />
                </span>
                <div>
                  <div className="font-semibold">
                    Included in the proposed model
                  </div>
                  <div className="mt-1 text-xs text-slate">
                    Final packaging is pending review
                  </div>
                </div>
              </div>
              <div className="mt-8 space-y-4">
                {included.map((item) => (
                  <div
                    key={item}
                    className="flex items-start gap-3 text-sm text-graphite"
                  >
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-voltage-violet" />
                    {item}
                  </div>
                ))}
              </div>
              <div className="mt-8 rounded-2xl bg-amber-50 p-4 text-xs leading-5 text-amber-900">
                <CircleAlert className="mb-2 h-4 w-4" />
                Taxes, telephony, model costs, minimum recharge, refunds, and
                validity rules are still to be confirmed.
              </div>
            </motion.div>
          </div>
        </div>
      </section>
      <section className="px-5 py-16 sm:px-8 lg:py-24">
        <div className="mx-auto max-w-[1440px]">
          <div className="max-w-[720px]">
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              How a call may be priced
            </div>
            <h2 className="mt-5 text-[clamp(2.8rem,5vw,4.7rem)] font-semibold leading-[.97] tracking-[-.06em]">
              Three cost layers to confirm.
            </h2>
            <p className="mt-5 text-base leading-7 text-slate">
              The final rate shown to a customer should make every applicable
              layer clear before calls begin.
            </p>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {layers.map((item, index) => (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.08 }}
                key={item.title}
                className="rounded-[28px] border border-mist p-7"
              >
                <div className="text-xs font-bold text-voltage-violet">
                  0{index + 1}
                </div>
                <h3 className="mt-8 text-xl font-semibold">{item.title}</h3>
                <p className="mt-3 text-sm leading-7 text-slate">{item.text}</p>
              </motion.div>
            ))}
          </div>
          <div className="mt-5 flex items-center gap-3 rounded-[24px] bg-fog p-5 text-sm text-graphite">
            <PhoneCall className="h-5 w-5 shrink-0 text-voltage-violet" />
            Final rates and billing rules will be added after commercial,
            provider, and compliance review.
          </div>
        </div>
      </section>
      <Footer />
    </main>
  );
}
