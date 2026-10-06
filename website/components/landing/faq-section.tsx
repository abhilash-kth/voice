"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Plus } from "lucide-react";

const faqs = [
  [
    "What can a Voxura agent do?",
    "Voxura agents can answer inbound calls or make outbound calls for configured business workflows, including support, reception, sales, HR, and finance-assistance use cases.",
  ],
  [
    "How do I create an agent?",
    "Describe the role and your business through the guided AI chat, or begin with a premade agent and customize it.",
  ],
  [
    "Which languages are supported?",
    "Voxura currently supports 11+ languages. The exact language and provider combination can be selected while configuring an agent.",
  ],
  [
    "How does billing work?",
    "Add funds to your wallet and pay by call usage. The applicable per-minute rate is shown before calls are launched.",
  ],
  [
    "Can Voxura make and receive calls?",
    "Yes. Agents can be configured for both inbound and outbound calling. Voxura does not currently provide phone numbers.",
  ],
  [
    "Are calls available after they finish?",
    "Yes. Calls are stored so your team can review conversations and campaign activity.",
  ],
];

export default function FaqSection() {
  const [open, setOpen] = useState(0);
  return (
    <section className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto grid max-w-[1440px] gap-12 lg:grid-cols-[.62fr_1.38fr] lg:gap-20">
        <div>
          <div className="text-xs font-bold uppercase tracking-[.12em] text-voltage-violet">
            Questions, answered
          </div>
          <h2 className="mt-5 text-[clamp(2.7rem,4.8vw,4.5rem)] font-semibold leading-[.98] tracking-[-.06em]">
            Everything before your first call.
          </h2>
          <p className="mt-5 max-w-[390px] text-base leading-7 text-slate">
            The essentials for creating, launching, and paying for an agent.
          </p>
        </div>
        <div className="border-t border-mist">
          {faqs.map(([question, answer], index) => (
            <div key={question} className="border-b border-mist">
              <button
                onClick={() => setOpen(open === index ? -1 : index)}
                className="flex w-full items-center justify-between gap-6 py-6 text-left text-base font-semibold sm:text-lg"
              >
                <span>{question}</span>
                <motion.span
                  animate={{ rotate: open === index ? 45 : 0 }}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-fog"
                >
                  <Plus className="h-4 w-4" />
                </motion.span>
              </button>
              <AnimatePresence initial={false}>
                {open === index && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.28 }}
                    className="overflow-hidden"
                  >
                    <p className="max-w-[720px] pb-6 pr-12 text-sm leading-7 text-slate sm:text-base">
                      {answer}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
