import Header from "@/components/landing/header";
import Footer from "@/components/landing/footer";

const sections = [
  [
    "1. Scope",
    "This policy explains how Voxura may collect, use, disclose, and protect information through its website and voice-agent platform. The final legal entity, registered address, data-protection contact, and effective date must be confirmed before publication.",
  ],
  [
    "2. Information provided by you",
    "We may process account and business details, contact information, billing information, agent instructions, scripts, knowledge sources, support enquiries, and other information you choose to submit.",
  ],
  [
    "3. Call and service data",
    "Depending on configuration and applicable law, the service may process phone numbers, call metadata, audio, transcripts, conversation outcomes, tool activity, agent settings, usage records, and diagnostic logs. Customers are responsible for providing required notices and obtaining required consents.",
  ],
  [
    "4. Website and device data",
    "We may collect IP address, browser and device information, pages viewed, referral information, approximate location, cookie identifiers, and security events. The final cookie and analytics inventory will be added before launch.",
  ],
  [
    "5. How information may be used",
    "Information may be used to provide and secure the service, run configured calls, maintain accounts, calculate usage, respond to enquiries, troubleshoot issues, improve product performance, prevent abuse, comply with law, and communicate service information.",
  ],
  [
    "6. Service providers and disclosures",
    "Information may be shared with authorised infrastructure, telephony, AI-model, speech, payment, analytics, security, and support providers where needed to operate the service. A final subprocessor list and data-location details will be published after provider review.",
  ],
  [
    "7. Data retention",
    "Information should be retained only for the period needed for the service, legal obligations, security, dispute resolution, and legitimate business purposes. Product-specific retention periods and customer deletion controls remain to be confirmed.",
  ],
  [
    "8. Security",
    "We intend to use administrative, technical, and organisational safeguards appropriate to the information processed. No method of storage or transmission is completely secure, and final security commitments must match verified production controls.",
  ],
  [
    "9. Your choices and rights",
    "Depending on applicable law, individuals may have rights to access, correct, delete, restrict, object to, or obtain a copy of personal data. Requests can be sent to hello@voxura.ai and may require identity verification.",
  ],
  [
    "10. International processing",
    "Providers may process information in more than one country. Where required, Voxura will use appropriate transfer mechanisms and contractual safeguards. Final hosting regions and transfer details must be documented before launch.",
  ],
  [
    "11. Children",
    "Voxura is designed for business use and is not intended for children. Customers must not knowingly configure agents to collect children’s personal data without a lawful basis and appropriate safeguards.",
  ],
  [
    "12. Updates and contact",
    "We may revise this policy as the product, providers, or legal requirements change. Questions and privacy requests can be sent to hello@voxura.ai. A formal privacy and grievance contact must be added before publication.",
  ],
];
export default function PrivacyContent() {
  return (
    <main id="top" className="bg-white text-midnight-ink">
      <Header />
      <section className="px-5 pb-20 pt-36 sm:px-8 lg:pt-44">
        <div className="mx-auto grid max-w-[1280px] gap-12 lg:grid-cols-[.55fr_1.45fr]">
          <aside className="lg:sticky lg:top-32 lg:self-start">
            <div className="text-xs font-bold uppercase tracking-[.14em] text-voltage-violet">
              Privacy
            </div>
            <h1 className="mt-5 text-[clamp(3.2rem,6vw,5.5rem)] font-semibold leading-[.9] tracking-[-.07em]">
              Privacy policy
            </h1>
            <p className="mt-6 text-sm text-slate">
              Draft · Last updated 2 October 2026
            </p>
            <div className="mt-7 rounded-[22px] bg-lavender-field p-5 text-xs leading-6 text-graphite">
              This draft must be aligned with the production data flow,
              providers, retention controls, and applicable law before launch.
            </div>
          </aside>
          <article className="overflow-hidden rounded-[34px] border border-mist bg-white shadow-[0_24px_70px_rgba(49,29,72,.07)]">
            {sections.map(([title, text], index) => (
              <section
                key={title}
                className="border-b border-mist p-6 last:border-0 sm:p-8"
              >
                <div className="flex gap-5">
                  <span className="mt-1 text-xs font-bold text-lavender-mist">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h2 className="text-xl font-semibold tracking-[-.02em]">
                      {title}
                    </h2>
                    <p className="mt-4 text-sm leading-7 text-slate">{text}</p>
                  </div>
                </div>
              </section>
            ))}
          </article>
        </div>
      </section>
      <Footer />
    </main>
  );
}
