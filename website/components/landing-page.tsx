import AgentsSection from "./landing/agents-section";
import BillingSection from "./landing/billing-section";
import ConversationSection from "./landing/conversation-section";
import ComplianceSection from "./landing/compliance-section";
import ScrollProgress from "./landing/scroll-progress";
import CreationSection from "./landing/creation-section";
import Footer from "./landing/footer";
import Header from "./landing/header";
import Hero from "./landing/hero";
import IndustryTrustSection from "./landing/industry-trust-section";
import LanguagesIndustries from "./landing/languages-industries";
import FaqSection from "./landing/faq-section";
import ProvidersSection from "./landing/providers-section";
import VisionAndCta from "./landing/vision-cta";

export default function LandingPage() {
  return (
    <div className="min-h-screen overflow-x-hidden bg-white text-midnight-ink selection:bg-lavender-field selection:text-ultra-violet">
      <ScrollProgress />
      <Header />
      <main>
        <Hero />
        <CreationSection />
        <ComplianceSection />
        <ConversationSection />
        <AgentsSection />
        <ProvidersSection />
        <BillingSection />
        <LanguagesIndustries />
        <VisionAndCta />
        <IndustryTrustSection />
        <FaqSection />
      </main>
      <Footer />
    </div>
  );
}
