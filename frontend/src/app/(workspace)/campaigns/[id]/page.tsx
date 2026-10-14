"use client";

import { useParams } from "next/navigation";
import CampaignDetail from "../components/CampaignDetail";

export default function CampaignDetailsPage() {
  const params = useParams<{ id: string }>();
  return <CampaignDetail campaignId={params.id} />;
}
