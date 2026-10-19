"use client";

import { motion } from "framer-motion";
import { ArrowRight, Mail, MessageSquare } from "lucide-react";
import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

export default function ContactPageContent() {
  const submitByEmail = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const subject = encodeURIComponent("Voxura voice agent enquiry");
    const body = encodeURIComponent(
      `Name: ${data.get("name")}\nPhone: ${data.get("phone")}\nEmail: ${data.get("email")}\n\nMessage:\n${data.get("message")}`,
    );
    window.location.href = `mailto:info@kriscent.in?subject=${subject}&body=${body}`;
  };

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

            <a
              href="mailto:info@kriscent.in"
              className="group mt-10 inline-flex items-center gap-4 rounded-[22px] border border-mist bg-white/80 p-4 pr-6 shadow-[0_16px_45px_rgba(61,28,95,.07)] backdrop-blur transition-all hover:-translate-y-1 hover:border-lavender-mist"
            >
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-lavender-field text-voltage-violet">
                <Mail className="h-5 w-5" />
              </span>
              <span>
                <span className="block text-[10px] font-bold uppercase tracking-[.13em] text-slate">
                  Email
                </span>
                <span className="mt-1 block text-sm font-semibold">
                  info@kriscent.in
                </span>
              </span>
            </a>
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
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white/10 text-lavender-mist">
                  <MessageSquare className="h-5 w-5" />
                </span>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-[.15em] text-white/40">
                    Start a conversation
                  </div>
                  <h2 className="mt-1 text-xl font-semibold">
                    Tell us what you need
                  </h2>
                </div>
              </div>

              <form
                onSubmit={submitByEmail}
                className="mt-8 rounded-[28px] bg-white p-5 text-midnight-ink sm:p-7"
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-graphite">
                    Name
                    <input
                      name="name"
                      required
                      autoComplete="name"
                      placeholder="Your name"
                      className="mt-2 h-12 w-full rounded-2xl border border-mist bg-fog/60 px-4 text-sm outline-none transition focus:border-lavender-mist focus:bg-white"
                    />
                  </label>
                  <label className="text-xs font-semibold text-graphite">
                    Phone
                    <input
                      name="phone"
                      required
                      type="tel"
                      autoComplete="tel"
                      placeholder="Your phone number"
                      className="mt-2 h-12 w-full rounded-2xl border border-mist bg-fog/60 px-4 text-sm outline-none transition focus:border-lavender-mist focus:bg-white"
                    />
                  </label>
                  <label className="text-xs font-semibold text-graphite sm:col-span-2">
                    Email
                    <input
                      name="email"
                      required
                      type="email"
                      autoComplete="email"
                      placeholder="you@company.com"
                      className="mt-2 h-12 w-full rounded-2xl border border-mist bg-fog/60 px-4 text-sm outline-none transition focus:border-lavender-mist focus:bg-white"
                    />
                  </label>
                  <label className="text-xs font-semibold text-graphite sm:col-span-2">
                    Message
                    <textarea
                      name="message"
                      required
                      rows={4}
                      placeholder="Tell us what your voice agent should handle."
                      className="mt-2 w-full resize-none rounded-2xl border border-mist bg-fog/60 p-4 text-sm leading-6 outline-none transition focus:border-lavender-mist focus:bg-white"
                    />
                  </label>
                </div>
                <p className="mt-4 text-[11px] leading-5 text-slate">
                  Submitting opens your email application with these details. No
                  information is stored on this website.
                </p>
                <button
                  type="submit"
                  className="group mt-5 inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-full bg-voltage-violet px-6 text-sm font-semibold text-white transition-all hover:-translate-y-0.5 hover:bg-ultra-violet"
                >
                  Continue by email{" "}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </button>
              </form>
            </div>
          </motion.div>
        </div>
      </section>
      <Footer />
    </main>
  );
}
