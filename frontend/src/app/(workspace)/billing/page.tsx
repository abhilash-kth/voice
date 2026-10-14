import BillingPanel from "@/app/(workspace)/billing/components/BillingPanel";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Billing | AI Voice Agent",
};

export default function BillingPage() {
  return <BillingPanel />;
}
