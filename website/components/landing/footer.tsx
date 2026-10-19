import { ArrowUpRight, Mail, Radio } from "lucide-react";
import { LogoMark } from "./primitives";

const groups = [
  {
    title: "Product",
    links: [
      ["Platform", "/#platform"],
      ["Voice agents", "/#agents"],
      ["Languages", "/#languages"],
      ["Pricing", "/pricing"],
    ],
  },
  {
    title: "Company",
    links: [
      ["About", "/about"],
      ["Contact", "/contact"],
      ["Kriscent Techno Hub", "https://kriscent.in/"],
    ],
  },
  {
    title: "Resources",
    links: [
      ["Compliance", "/#compliance"],
      ["FAQ", "/#faq"],
      ["Contact sales", "/contact"],
    ],
  },
  {
    title: "Legal",
    links: [
      ["Privacy policy", "/privacy-policy"],
      ["Terms & conditions", "/terms-and-conditions"],
    ],
  },
];

const socials = [
  { label: "Instagram", mark: "IG" },
  { label: "YouTube", mark: "YT" },
  { label: "LinkedIn", mark: "in" },
  { label: "X / Twitter", mark: "X" },
];

export default function Footer() {
  return (
    <footer className="px-5 pb-6 sm:px-8">
      <div className="relative mx-auto flex min-h-[590px] max-w-[1440px] flex-col justify-between overflow-hidden rounded-[44px] bg-midnight-ink p-8 text-white sm:p-12 lg:p-20">
        <div className="pointer-events-none absolute -right-32 -top-40 h-[430px] w-[430px] rounded-full bg-voltage-violet/20 blur-[110px]" />
        <div className="pointer-events-none absolute -bottom-48 left-[18%] h-96 w-96 rounded-full bg-[#a94df0]/10 blur-[120px]" />

        <div className="relative grid gap-16 border-b border-white/10 pb-16 lg:grid-cols-[1fr_1.55fr] lg:gap-24 lg:pb-24">
          <div className="[&>a>span:first-child]:h-14 [&>a>span:first-child]:w-14 [&>a>span:first-child]:rounded-[18px] [&>a>span:first-child>svg]:h-6 [&>a>span:first-child>svg]:w-6 [&>a>span:last-child]:text-3xl [&>a>span:last-child]:text-white">
            <LogoMark />
            <p className="mt-7 max-w-[430px] text-base leading-8 text-white/50">
              AI voice agents for inbound calls, outbound conversations, and
              multilingual business operations.
            </p>
            <a
              href="mailto:info@kriscent.in"
              className="group mt-7 inline-flex items-center gap-3 rounded-full border border-white/12 bg-white/[.055] px-5 py-3 text-sm font-semibold transition-colors hover:bg-white/10"
            >
              <Mail className="h-4 w-4 text-lavender-mist" />
              info@kriscent.in
              <ArrowUpRight className="h-3.5 w-3.5 text-white/35 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-white" />
            </a>
          </div>

          <div className="grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-4">
            {groups.map((group) => (
              <div key={group.title}>
                <div className="text-[11px] font-bold uppercase tracking-[.14em] text-white/35">
                  {group.title}
                </div>
                <div className="mt-6 space-y-4">
                  {group.links.map(([label, href]) => (
                    <a
                      key={label}
                      href={href}
                      target={href.startsWith("http") ? "_blank" : undefined}
                      rel={href.startsWith("http") ? "noreferrer" : undefined}
                      className="group flex w-fit items-center gap-1.5 text-sm text-white/62 transition-colors hover:text-white"
                    >
                      {label}
                      <ArrowUpRight className="h-3 w-3 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:opacity-100" />
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 flex items-center justify-center flex-wrap md:flex-nowrap gap-2.5">
          {socials.map(({ label, mark }) => (
            <a
              key={label}
              href="#"
              aria-label={label}
              className="group inline-flex min-h-11 items-center gap-2.5 rounded-full border border-white/10 bg-white/[.045] px-3.5 text-xs font-semibold text-white/55 transition-all hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/10 hover:text-white"
            >
              <span className="grid h-6 w-6 place-items-center rounded-full bg-white/10 text-[9px] font-bold text-lavender-mist">
                {mark}
              </span>
              {label}
              <ArrowUpRight className="h-3 w-3 text-white/25 transition-colors group-hover:text-white" />
            </a>
          ))}
        </div>

        <div className="relative flex flex-col gap-5 pt-10 text-xs text-white/35 sm:flex-row sm:items-center sm:justify-between">
          <span>
            © 2026 Voxura. A product developed by Kriscent Techno Hub Pvt Ltd.
          </span>
          <span className="flex items-center gap-2">
            <Radio className="h-3.5 w-3.5 text-lavender-mist" /> Built for real
            business conversations
          </span>
        </div>
      </div>
    </footer>
  );
}
