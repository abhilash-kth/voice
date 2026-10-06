"use client";

import { motion } from "framer-motion";
import {
  ArrowRight,
  Building2,
  Check,
  Mail,
  MessageSquare,
  PhoneCall,
} from "lucide-react";
import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

const fields = ["Full name", "Work email", "Company name", "Phone number"];
export default function ContactPageContent() {
  return (
    <main id="top" className="min-h-screen bg-white text-midnight-ink">
      <Header />
      <section className="relative overflow-hidden px-5 pb-16 pt-36 sm:px-8 lg:pb-24 lg:pt-44">
        <div className="absolute left-[8%] top-20 h-72 w-72 rounded-full bg-lavender-field/70 blur-[90px]" />
        <div className="absolute right-[5%] top-36 h-80 w-80 rounded-full bg-amber-100/55 blur-[100px]" />
        <div className="relative mx-auto grid max-w-[1440px] gap-12 lg:grid-cols-[.8fr_1.2fr] lg:items-start">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Contact Voxura
            </div>
            <h1 className="mt-5 max-w-[650px] text-[clamp(3.5rem,7vw,6.8rem)] font-semibold leading-[.9] tracking-[-.07em]">
              Let’s plan your voice agent.
            </h1>
            <p className="mt-7 max-w-[540px] text-lg leading-8 text-slate">
              Tell us what calls you want to handle. We’ll use the conversation
              to understand the role, languages, volume, and setup you need.
            </p>
            <div className="mt-10 space-y-3">
              {[
                [Mail, "Email us", "hello@voxura.ai"],
                [
                  PhoneCall,
                  "Discuss your workflow",
                  "Inbound, outbound, or both",
                ],
                [
                  Building2,
                  "For business teams",
                  "Self-serve and assisted setup",
                ],
              ].map(([Icon, title, text]) => {
                const I = Icon as typeof Mail;
                return (
                  <div
                    key={title as string}
                    className="flex items-center gap-4 rounded-[22px] border border-mist bg-white/75 p-4 backdrop-blur"
                  >
                    <span className="grid h-11 w-11 place-items-center rounded-2xl bg-fog text-voltage-violet">
                      <I className="h-5 w-5" />
                    </span>
                    <div>
                      <div className="text-sm font-semibold">
                        {title as string}
                      </div>
                      <div className="mt-1 text-xs text-slate">
                        {text as string}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
            className="rounded-[38px] border border-mist bg-white p-6 shadow-[0_28px_80px_rgba(61,28,95,.1)] sm:p-9"
          >
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-voltage-violet text-white">
                <MessageSquare className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-xl font-semibold">
                  Tell us what you’re building
                </h2>
                <p className="mt-1 text-xs text-slate">
                  We’ll reply using the contact details below.
                </p>
              </div>
            </div>
            <form className="mt-8" onSubmit={(event) => event.preventDefault()}>
              <div className="grid gap-4 sm:grid-cols-2">
                {fields.map((field) => (
                  <label
                    key={field}
                    className="text-xs font-semibold text-graphite"
                  >
                    {field}
                    <input
                      required={field !== "Phone number"}
                      type={field.includes("email") ? "email" : "text"}
                      placeholder={field}
                      className="mt-2 h-12 w-full rounded-2xl border border-mist bg-fog/60 px-4 text-sm outline-none transition focus:border-lavender-mist focus:bg-white"
                    />
                  </label>
                ))}
              </div>
              <label className="mt-4 block text-xs font-semibold text-graphite">
                What should your agent handle?
                <textarea
                  rows={5}
                  placeholder="Example: qualify inbound enquiries in Hindi and English, then schedule a follow-up."
                  className="mt-2 w-full resize-none rounded-2xl border border-mist bg-fog/60 p-4 text-sm leading-6 outline-none transition focus:border-lavender-mist focus:bg-white"
                />
              </label>
              <div className="mt-4 flex items-start gap-2 text-xs leading-5 text-slate">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-voltage-violet" />
                By submitting, you agree that Voxura may contact you about this
                enquiry.
              </div>
              <button
                type="submit"
                className="group mt-6 inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-full bg-voltage-violet px-6 text-sm font-semibold text-white transition-all hover:-translate-y-0.5 hover:bg-ultra-violet"
              >
                Send enquiry{" "}
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </button>
            </form>
          </motion.div>
        </div>
      </section>
      <Footer />
    </main>
  );
}
