import { Metadata } from "next";
import CampaignList from "./components/CampaignList";

export const metadata:Metadata = {
  title : "Campaigns | AI Voice Calling"
}

export default function CampaignsPage() {
  return <CampaignList />;
}
