"use client";
import { motion } from "framer-motion";
import { ArrowRight, Check, FileSpreadsheet, Pause } from "lucide-react";
import { cn } from "@/lib/utils";
import { ArrowButton, SectionHeading } from "./primitives";
export default function CampaignSection() {
  return (
    <section id="campaigns" className="px-5 py-14 sm:px-8 sm:py-16 lg:py-20">
      <div className="mx-auto max-w-[1440px]">
        <div className="flex flex-col justify-between gap-7 lg:flex-row lg:items-end">
          <SectionHeading eyebrow="Bulk campaigns" title={<>From spreadsheet<br />to conversations.</>} body="Upload your leads, choose an agent, and launch structured outbound calls without dialing one contact at a time." />
          <ArrowButton dark href="#final-cta">Create a campaign</ArrowButton>
        </div>
        <div className="mt-14 grid gap-4 lg:grid-cols-[.7fr_1.3fr]">
          <motion.div initial={{ opacity: 0, x: -20 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} className="flex min-h-[520px] flex-col justify-between rounded-[32px] bg-midnight-ink p-7 text-white sm:p-9">
            <div>
              <div className="flex items-center justify-between"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-white/10"><FileSpreadsheet className="h-5 w-5 text-lavender-mist" /></span><span className="rounded-full bg-emerald-400/10 px-3 py-1.5 text-xs font-semibold text-emerald-300">Ready</span></div>
              <h3 className="mt-9 text-3xl font-semibold tracking-[-.04em]">October lead follow-up</h3>
              <p className="mt-3 text-sm leading-6 text-white/50">leads_october.csv</p>
              <div className="mt-8 space-y-3">
                {["1,240 contacts mapped", "Sales agent selected", "Hindi + English", "Wallet balance checked"].map((item) => <div key={item} className="flex items-center gap-3 rounded-xl bg-white/[.06] p-3.5 text-sm"><Check className="h-4 w-4 text-emerald-300" />{item}</div>)}
              </div>
            </div>
            <button className="mt-9 flex items-center justify-center gap-2 rounded-xl bg-white px-5 py-4 text-sm font-semibold text-midnight-ink">Launch campaign <ArrowRight className="h-4 w-4" /></button>
          </motion.div>
          <motion.div initial={{ opacity: 0, x: 20 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} className="overflow-hidden rounded-[32px] border border-mist bg-white p-5 sm:p-8">
            <div className="flex flex-col gap-5 border-b border-mist pb-6 sm:flex-row sm:items-center sm:justify-between">
              <div><div className="text-xs font-bold uppercase tracking-[.14em] text-slate">Campaign progress</div><h3 className="mt-2 text-2xl font-semibold tracking-[-.03em]">Calls in motion</h3></div>
              <div className="flex gap-2"><span className="rounded-full bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">Live</span><button className="grid h-9 w-9 place-items-center rounded-full border border-mist"><Pause className="h-3.5 w-3.5" /></button></div>
            </div>
            <div className="grid grid-cols-3 gap-2 py-6">
              {[["Completed", "786"], ["In progress", "18"], ["Remaining", "436"]].map(([key, val], i) => <div key={key} className={cn("rounded-2xl p-4", i === 0 ? "bg-lavender-field" : "bg-fog")}><div className="text-[10px] font-bold uppercase tracking-wider text-slate">{key}</div><div className="mt-2 text-2xl font-semibold tracking-[-.04em]">{val}</div></div>)}
            </div>
            <div className="space-y-2">
              {[
                ["Priya Sharma", "Completed", "01:48", "Hindi"],
                ["Rohan Mehta", "On call", "00:36", "English"],
                ["Ananya Iyer", "Completed", "02:11", "English"],
                ["Kabir Singh", "Dialing", "—", "Hindi"],
              ].map(([name, status, time, language]) => <div key={name} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-2xl border border-mist/80 p-3.5 sm:grid-cols-[1fr_100px_60px_70px]"><div className="flex items-center gap-3"><span className="grid h-8 w-8 place-items-center rounded-full bg-fog text-xs font-bold text-voltage-violet">{name[0]}</span><span className="text-sm font-semibold">{name}</span></div><span className={cn("text-right text-xs font-semibold sm:text-left", status === "On call" ? "text-voltage-violet" : "text-slate")}>{status}</span><span className="hidden text-xs text-slate sm:block">{time}</span><span className="hidden text-xs text-slate sm:block">{language}</span></div>)}
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

