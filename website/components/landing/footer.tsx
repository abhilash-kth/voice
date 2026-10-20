import { ArrowUpRight, Mail, Radio } from "lucide-react";
import { LogoMark } from "./primitives";

const groups = [
  {
    title: "Product",
    links: [
      ["Platform", "/#platform"],
      ["Voice agents", "/#agents"],
      ["Languages", "/#languages"],
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
    title: "Legal",
    links: [
      ["Compliance", "/#compliance"],
      ["Privacy policy", "/privacy-policy"],
      ["Terms & conditions", "/terms-and-conditions"],
    ],
  },
];

const socials = [
  {
    label: "Facebook",
    platform: "facebook",
    href: "https://www.facebook.com/KriscentTechnoHub/",
  },
  {
    label: "Instagram",
    platform: "instagram",
    href: "https://www.instagram.com/kriscenttechnohub/",
  },
  {
    label: "LinkedIn",
    platform: "linkedin",
    href: "https://www.linkedin.com/company/kriscenttechnohub/",
  },
  {
    label: "YouTube",
    platform: "youtube",
    href: "https://www.youtube.com/channel/UC_xjC_bZgHtGWwGfRN4Qnug",
  },
  { label: "X", platform: "x", href: "https://x.com/kriscent_kth" },
];

function SocialIcon({ platform }: { platform: string }) {
  if (platform === "facebook")
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-4 w-4 fill-current"
      >
        <path d="M14 8.5V7c0-.8.5-1 1-1h2V2.2A27 27 0 0 0 14.1 2C11.2 2 9 3.8 9 7.2v1.3H6v4h3V22h4.2v-9.5h3.2l.6-4H14Z" />
      </svg>
    );
  if (platform === "instagram")
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-4 w-4 fill-none stroke-current"
        strokeWidth="2"
      >
        <rect x="3" y="3" width="18" height="18" rx="5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="17.5" cy="6.5" r="1" className="fill-current stroke-none" />
      </svg>
    );
  if (platform === "linkedin")
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-4 w-4 fill-current"
      >
        <path d="M5.2 7.8A2.4 2.4 0 1 0 5.2 3a2.4 2.4 0 0 0 0 4.8ZM3.2 9.5h4V21h-4V9.5ZM9.5 9.5h3.8v1.6h.1c.5-1 1.8-2.1 3.7-2.1 4 0 4.7 2.6 4.7 6V21h-4v-5.3c0-1.3 0-3-1.9-3s-2.2 1.4-2.2 2.9V21h-4V9.5Z" />
      </svg>
    );
  if (platform === "youtube")
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-4 w-4 fill-current"
      >
        <path d="M22 7.2a3 3 0 0 0-2.1-2.1C18 4.6 12 4.6 12 4.6s-6 0-7.9.5A3 3 0 0 0 2 7.2 31 31 0 0 0 1.5 12c0 1.6.1 3.2.5 4.8a3 3 0 0 0 2.1 2.1c1.9.5 7.9.5 7.9.5s6 0 7.9-.5a3 3 0 0 0 2.1-2.1c.4-1.6.5-3.2.5-4.8s-.1-3.2-.5-4.8ZM9.8 15.2V8.8l5.5 3.2-5.5 3.2Z" />
      </svg>
    );
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="h-4 w-4 fill-current"
    >
      <path d="M18.9 2H22l-6.8 7.8L23.2 22H17l-4.9-6.4L6.5 22H3.4l7.2-8.2L2.8 2H9l4.4 5.8L18.9 2Zm-1.1 17.9h1.7L8.1 4H6.3l11.5 15.9Z" />
    </svg>
  );
}

export default function Footer() {
  return (
    <footer className="px-5 pb-6 sm:px-8">
      <div className="relative mx-auto flex min-h-[590px] max-w-[1440px] flex-col justify-between overflow-hidden rounded-[44px] bg-midnight-ink p-8 text-white sm:p-12 lg:p-20">
        <div className="pointer-events-none absolute -right-32 -top-40 h-[430px] w-[430px] rounded-full bg-voltage-violet/20 blur-[110px]" />
        <div className="pointer-events-none absolute -bottom-48 left-[18%] h-96 w-96 rounded-full bg-[#a94df0]/10 blur-[120px]" />

        <div className="relative grid gap-16 pb-10 lg:grid-cols-[1fr_1.35fr] lg:gap-24 lg:pb-12">
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
            <div className="mt-8 flex flex-wrap gap-2.5">
              {socials.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={social.label}
                  title={social.label}
                  className="grid h-11 w-11 place-items-center rounded-full border border-white/10 bg-white/[.045] text-white/55 transition-all hover:-translate-y-1 hover:border-white/20 hover:bg-white/10 hover:text-white"
                >
                  <SocialIcon platform={social.platform} />
                </a>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-10 gap-y-10 sm:grid-cols-3">
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

        <div className="relative flex flex-col gap-7 border-y border-white/10 py-8 sm:flex-row sm:items-center sm:justify-between lg:py-10">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[.16em] text-lavender-mist">
              Start a conversation
            </div>
            <h3 className="mt-3 max-w-[700px] text-[clamp(1.8rem,3.2vw,3.2rem)] font-semibold leading-[1.05] tracking-[-.05em]">
              Ready to put an AI voice agent to work?
            </h3>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2.5">
            <a
              href="https://agents.kriscenttechnohub.com/"
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-12 items-center justify-center rounded-full border border-white/12 bg-white/[.055] px-5 text-sm font-semibold text-white transition-colors hover:bg-white/10"
            >
              Login
            </a>
            <a
              href="/contact"
              className="group inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-white px-5 text-sm font-semibold text-midnight-ink transition-transform hover:-translate-y-0.5"
            >
              Contact sales{" "}
              <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </a>
          </div>
        </div>

        <div className="relative flex flex-col gap-5 pt-8 text-xs text-white/35 sm:flex-row sm:items-center sm:justify-between">
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
