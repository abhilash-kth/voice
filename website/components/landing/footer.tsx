import { ArrowUpRight, Mail, Radio } from "lucide-react";
import { LogoMark } from "./primitives";

const groups = [
  {
    title: "Product",
    links: [
      ["Platform", "/#platform"],
      ["AI agents", "/#agents"],
      ["Languages", "/#languages"],
      ["Pricing", "/pricing"],
    ],
  },
  {
    title: "Company",
    links: [
      ["About", "/about"],
      ["Contact", "/contact"],
      ["Compliance", "/#compliance"],
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

export default function Footer() {
  return (
    <footer className="px-5 pb-6 sm:px-8">
      <div className="mx-auto max-w-[1440px] overflow-hidden rounded-[36px] bg-midnight-ink p-7 text-white sm:p-8 lg:p-10">
        <div className="grid gap-14 border-b border-white/10 pb-14 lg:grid-cols-[1.35fr_1.65fr]">
          <div className="[&>a>span:last-child]:text-white">
            <LogoMark />
            <p className="mt-6 max-w-[380px] text-sm leading-7 text-white/50">
              AI voice agents for inbound calls, outbound conversations, and
              multilingual business operations.
            </p>
            <a
              href="mailto:info@kriscent.in"
              className="mt-7 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[.06] px-4 py-2.5 text-sm font-semibold transition-colors hover:bg-white/10"
            >
              <Mail className="h-4 w-4 text-lavender-mist" /> info@kriscent.in
            </a>
          </div>
          <div className="grid grid-cols-2 gap-9 sm:grid-cols-3">
            {groups.map((group) => (
              <div key={group.title}>
                <div className="text-xs font-bold uppercase tracking-[.12em] text-white/35">
                  {group.title}
                </div>
                <div className="mt-5 space-y-3">
                  {group.links.map(([label, href]) => (
                    <a
                      key={label}
                      href={href}
                      className="group flex w-fit items-center gap-1 text-sm text-white/65 transition-colors hover:text-white"
                    >
                      {label}
                      <ArrowUpRight className="h-3 w-3 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100" />
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-5 pt-7 text-xs text-white/35 sm:flex-row sm:items-center sm:justify-between">
          <span>© 2026 Voxura. Working product name.</span>
          <span className="flex items-center gap-2">
            <Radio className="h-3.5 w-3.5 text-lavender-mist" /> Built for real
            business conversations
          </span>
        </div>
      </div>
    </footer>
  );
}
