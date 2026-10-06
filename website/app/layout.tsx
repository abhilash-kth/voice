import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";

import "./globals.css";

const sora = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-sora",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Voxura | AI Voice Agents for Business",
  description:
    "Create multilingual AI voice agents for inbound calls, outbound campaigns, and everyday business conversations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sora.className} ${sora.variable}`}>{children}</body>
    </html>
  );
}
